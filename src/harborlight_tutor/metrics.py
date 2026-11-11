"""Offline metrics: RAGAS non-LLM scores, refusal correctness, hit rate, and MRR."""

import asyncio
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from harborlight_tutor.models import EvalQuestion, PipelineOutput

OFFLINE_METRICS = (
    "non_llm_context_recall",
    "string_presence",
    "refusal_correctness",
    "hit_rate",
    "mrr",
)

LIVE_METRICS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)

JUDGE_NOT_RUN_REASON = (
    "No live judge was run for this snapshot. "
    "LLM judge scores are produced only in live mode and are not recorded here."
)


@dataclass
class MetricValue:
    name: str
    value: float
    threshold: float

    @property
    def passed(self) -> bool:
        return self.value + 1e-9 >= self.threshold


@dataclass
class RowScore:
    id: str
    question: str
    expected_behavior: str
    response: str
    retrieved_ids: list[str]
    shown_ids: list[str]
    retrieved_texts: list[str]
    reference_answer: str
    hit: bool | None
    refusal_ok: bool
    reasons: list[str]

    @property
    def failed(self) -> bool:
        if not self.refusal_ok:
            return True
        return self.hit is False


@dataclass
class VariantEval:
    variant: str
    provider: str
    metrics: list[MetricValue]
    rows: list[RowScore]

    @property
    def passed(self) -> bool:
        return all(metric.passed for metric in self.metrics)

    def metric(self, name: str) -> MetricValue:
        for item in self.metrics:
            if item.name == name:
                return item
        raise KeyError(name)


def score_outputs(
    questions: Sequence[EvalQuestion],
    outputs: Sequence[PipelineOutput],
    chunk_text: Mapping[str, str],
    thresholds: Mapping[str, float],
    variant: str,
    provider: str,
) -> VariantEval:
    missing = [name for name in OFFLINE_METRICS if name not in thresholds]
    extra = [name for name in thresholds if name not in OFFLINE_METRICS]
    if missing or extra:
        raise ValueError(
            f"offline thresholds must be {OFFLINE_METRICS}, missing={missing} extra={extra}"
        )
    by_id = {output.question_id: output for output in outputs}
    if set(by_id) != {question.id for question in questions}:
        raise ValueError("pipeline outputs do not match the question ids")

    rows: list[RowScore] = []
    recall_pairs: list[tuple[list[str], list[str]]] = []
    presence_pairs: list[tuple[str, str]] = []
    hits: list[float] = []
    reciprocal_ranks: list[float] = []
    refusal_flags: list[float] = []

    for question in questions:
        output = by_id[question.id]
        reasons: list[str] = []
        refusal_ok = _phrases_ok(question, output.response, reasons)
        hit: bool | None = None
        if question.grade_retrieval:
            relevant = set(question.reference_context_ids)
            rank = _rank(output.retrieved_ids, relevant)
            hit = rank is not None
            hits.append(1.0 if hit else 0.0)
            reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
            if not hit:
                reasons.append("reference context was not retrieved")
            reference_texts = [chunk_text[chunk_id] for chunk_id in question.reference_context_ids]
            recall_pairs.append((output.retrieved_texts, reference_texts))
        if question.expected_behavior == "answer":
            presence_pairs.append((question.reference_answer, output.response))
        refusal_flags.append(1.0 if refusal_ok else 0.0)
        rows.append(
            RowScore(
                id=question.id,
                question=question.question,
                expected_behavior=question.expected_behavior,
                response=output.response,
                retrieved_ids=list(output.retrieved_ids),
                shown_ids=list(output.shown_ids),
                retrieved_texts=list(output.retrieved_texts),
                reference_answer=question.reference_answer,
                hit=hit,
                refusal_ok=refusal_ok,
                reasons=reasons,
            )
        )

    recall_scores, presence_scores = asyncio.run(_non_llm_scores(recall_pairs, presence_pairs))
    scores = {
        "non_llm_context_recall": _mean(recall_scores),
        "string_presence": _mean(presence_scores),
        "refusal_correctness": _mean(refusal_flags),
        "hit_rate": _mean(hits),
        "mrr": _mean(reciprocal_ranks),
    }
    metrics = [
        MetricValue(name=name, value=scores[name], threshold=float(thresholds[name]))
        for name in OFFLINE_METRICS
    ]
    return VariantEval(variant=variant, provider=provider, metrics=metrics, rows=rows)


def _phrases_ok(question: EvalQuestion, response: str, reasons: list[str]) -> bool:
    folded = response.casefold()
    ok = True
    for phrase in question.must_include:
        if phrase.casefold() not in folded:
            reasons.append(f"missing required phrase: {phrase}")
            ok = False
    for phrase in question.must_not_include:
        if phrase.casefold() in folded:
            reasons.append(f"contains forbidden phrase: {phrase}")
            ok = False
    return ok


def _rank(retrieved_ids: Sequence[str], relevant: set[str]) -> int | None:
    for index, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant:
            return index
    return None


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty metric")
    return float(sum(values) / len(values))


async def _non_llm_scores(
    recall_pairs: Sequence[tuple[list[str], list[str]]],
    presence_pairs: Sequence[tuple[str, str]],
) -> tuple[list[float], list[float]]:
    """NonLLMContextRecall still lives on ragas.metrics in 0.4.3. StringPresence is collections."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from ragas.dataset_schema import SingleTurnSample
        from ragas.metrics import NonLLMContextRecall
        from ragas.metrics.collections import StringPresence

    recall_metric = NonLLMContextRecall()
    presence_metric = StringPresence()
    recall_scores: list[float] = []
    for retrieved, reference in recall_pairs:
        if not retrieved:
            recall_scores.append(0.0)
            continue
        sample = SingleTurnSample(
            retrieved_contexts=list(retrieved),
            reference_contexts=list(reference),
        )
        recall_scores.append(float(await recall_metric.single_turn_ascore(sample)))
    presence_scores: list[float] = []
    for reference_answer, answer_text in presence_pairs:
        result = await presence_metric.ascore(reference=reference_answer, response=answer_text)
        presence_scores.append(float(result.value))
    return recall_scores, presence_scores
