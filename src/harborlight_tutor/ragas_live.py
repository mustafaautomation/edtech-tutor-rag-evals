"""Live RAGAS scoring with the 0.4 collections API.

Faithfulness, answer relevancy, context precision, and context recall are
LLM-judged. They run only when a key is present. This module does not invent
scores when the key is missing.
"""

import asyncio
import os
from collections.abc import Sequence
from typing import Any

from harborlight_tutor.metrics import LIVE_METRICS, RowScore


class LiveEvalUnavailable(RuntimeError):
    """Raised when live eval is requested without the provider's API key."""


def require_openai_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise LiveEvalUnavailable("OPENAI_API_KEY is not set, so live eval did not run.")


def require_anthropic_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LiveEvalUnavailable("ANTHROPIC_API_KEY is not set, so live eval did not run.")


def score_live(
    rows: Sequence[RowScore], judge_model: str, embedding_model: str
) -> dict[str, float]:
    """Average RAGAS collections metrics on answer rows. Requires OPENAI_API_KEY."""
    require_openai_key()
    answer_rows = [row for row in rows if row.expected_behavior == "answer"]
    if not answer_rows:
        raise ValueError("live metrics need at least one answer question")
    return asyncio.run(_score(answer_rows, judge_model, embedding_model))


async def _score(
    rows: Sequence[RowScore], judge_model: str, embedding_model: str
) -> dict[str, float]:
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    client = AsyncOpenAI()
    llm = llm_factory(judge_model, client=client)
    embeddings: Any = embedding_factory("openai", model=embedding_model, client=client)
    faithfulness = Faithfulness(llm=llm)
    relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)
    precision = ContextPrecisionWithReference(llm=llm)
    recall = ContextRecall(llm=llm)

    scores: dict[str, list[float]] = {name: [] for name in LIVE_METRICS}
    for row in rows:
        contexts = list(row.retrieved_texts)
        faith = await faithfulness.ascore(
            user_input=row.question,
            response=row.response,
            retrieved_contexts=contexts,
        )
        rel = await relevancy.ascore(user_input=row.question, response=row.response)
        prec = await precision.ascore(
            user_input=row.question,
            reference=row.reference_answer,
            retrieved_contexts=contexts,
        )
        rec = await recall.ascore(
            user_input=row.question,
            retrieved_contexts=contexts,
            reference=row.reference_answer,
        )
        scores["faithfulness"].append(_value(faith))
        scores["answer_relevancy"].append(_value(rel))
        scores["context_precision"].append(_value(prec))
        scores["context_recall"].append(_value(rec))
    return {name: sum(values) / len(values) for name, values in scores.items()}


def _value(result: Any) -> float:
    if hasattr(result, "value"):
        return float(result.value)
    return float(result)
