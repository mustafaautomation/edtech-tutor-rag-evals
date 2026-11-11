"""Wire the corpus, pipelines, metrics, and reports."""

import json
import os
from pathlib import Path
from typing import Any

import yaml

from harborlight_tutor.corpus import Catalog, load_corpus
from harborlight_tutor.embeddings import HashingEmbedder
from harborlight_tutor.evalset import load_questions
from harborlight_tutor.faiss_index import FaissIndex
from harborlight_tutor.metrics import (
    JUDGE_NOT_RUN_REASON,
    LIVE_METRICS,
    OFFLINE_METRICS,
    MetricValue,
    VariantEval,
    score_outputs,
)
from harborlight_tutor.models import EvalQuestion
from harborlight_tutor.paths import (
    corpus_dir,
    questions_path,
    settings_path,
    thresholds_path,
)
from harborlight_tutor.pgvector_store import PgVectorIndex, PgVectorRetriever, connect
from harborlight_tutor.pipeline import (
    DECOY_CHUNK_ID,
    VARIANT_ORDER,
    BadRetriever,
    EmbeddingRetriever,
    Pipeline,
    indexable_chunks,
)
from harborlight_tutor.prompts import GUARDED_SYSTEM, UNGUARDED_SYSTEM
from harborlight_tutor.providers import (
    AnthropicProvider,
    DeterministicTutor,
    LLMProvider,
    OpenAIProvider,
)
from harborlight_tutor.ragas_live import (
    require_anthropic_key,
    require_openai_key,
    score_live,
)
from harborlight_tutor.report import Comparison, render_html, render_markdown


class Settings:
    def __init__(
        self,
        top_k: int,
        embedding_dim: int,
        openai_chat_model: str,
        openai_embedding_model: str,
        anthropic_model: str,
        judge_model: str,
    ) -> None:
        self.top_k = top_k
        self.embedding_dim = embedding_dim
        self.openai_chat_model = openai_chat_model
        self.openai_embedding_model = openai_embedding_model
        self.anthropic_model = anthropic_model
        self.judge_model = judge_model


def load_settings(path: Path | None = None) -> Settings:
    raw = _mapping(path or settings_path())
    defaults = Settings(
        5, 384, "gpt-4o-mini", "text-embedding-3-small", "claude-sonnet-4-5", "gpt-4o-mini"
    )
    return Settings(
        top_k=_int_field(raw, "top_k", defaults.top_k),
        embedding_dim=_int_field(raw, "embedding_dim", defaults.embedding_dim),
        openai_chat_model=_str_field(raw, "openai_chat_model", defaults.openai_chat_model),
        openai_embedding_model=_str_field(
            raw, "openai_embedding_model", defaults.openai_embedding_model
        ),
        anthropic_model=_str_field(raw, "anthropic_model", defaults.anthropic_model),
        judge_model=_str_field(raw, "judge_model", defaults.judge_model),
    )


def load_threshold_groups(path: Path | None = None) -> dict[str, dict[str, float]]:
    raw = _mapping(path or thresholds_path())
    return {
        "offline": _float_group(raw, "offline", OFFLINE_METRICS),
        "live": _float_group(raw, "live", LIVE_METRICS),
    }


def run_offline(gated_variant: str = "improved") -> Comparison:
    _check_variant(gated_variant)
    catalog, questions, settings = _load_all()
    thresholds = load_threshold_groups()["offline"]
    pipelines = build_offline_pipelines(catalog, settings)
    variants = {
        name: _score_pipeline(pipelines[name], questions, catalog, thresholds)
        for name in VARIANT_ORDER
    }
    return Comparison(
        mode="offline",
        variants=variants,
        gated_variant=gated_variant,
        notes=[
            "Offline generation uses the deterministic tutor. No API key is read.",
            JUDGE_NOT_RUN_REASON,
            "non_llm_context_recall and string_presence are RAGAS non-LLM metrics. "
            "refusal_correctness, hit_rate, and mrr are project checks.",
        ],
    )


def run_live(gated_variant: str = "improved", provider_name: str = "openai") -> Comparison:
    _check_variant(gated_variant)
    if provider_name == "openai":
        require_openai_key()
    elif provider_name == "anthropic":
        require_anthropic_key()
        require_openai_key()
    else:
        raise ValueError(f"unknown live provider {provider_name}")
    catalog, questions, settings = _load_all()
    groups = load_threshold_groups()
    provider = _live_provider(provider_name, settings)
    pipeline = build_variant(catalog, settings, gated_variant, provider)
    variant_eval = _score_pipeline(pipeline, questions, catalog, groups["offline"])
    live_scores = score_live(
        variant_eval.rows, settings.judge_model, settings.openai_embedding_model
    )
    for name in LIVE_METRICS:
        variant_eval.metrics.append(
            MetricValue(name=name, value=live_scores[name], threshold=groups["live"][name])
        )
    return Comparison(
        mode="live",
        variants={gated_variant: variant_eval},
        gated_variant=gated_variant,
        notes=[
            f"Live generation used the {provider_name} provider.",
            "RAGAS faithfulness, answer relevancy, context precision, and context recall "
            "are averaged on questions labelled answer. Refusal rows are scored by "
            "refusal_correctness instead.",
        ],
    )


def build_offline_pipelines(catalog: Catalog, settings: Settings) -> dict[str, Pipeline]:
    guarded = DeterministicTutor("guarded")
    unguarded = DeterministicTutor("unguarded")
    shared = _embedding_retriever(catalog, settings)
    bad = BadRetriever([catalog.by_id[DECOY_CHUNK_ID]])
    return {
        "improved": _pipeline(
            catalog, settings, "improved", shared, guarded, "guarded", GUARDED_SYSTEM
        ),
        "no_guardrail": _pipeline(
            catalog, settings, "no_guardrail", shared, unguarded, "unguarded", UNGUARDED_SYSTEM
        ),
        "bad_retriever": _pipeline(
            catalog, settings, "bad_retriever", bad, guarded, "guarded", GUARDED_SYSTEM
        ),
    }


def build_variant(
    catalog: Catalog,
    settings: Settings,
    variant: str,
    provider: LLMProvider,
) -> Pipeline:
    _check_variant(variant)
    if variant == "bad_retriever":
        retriever: EmbeddingRetriever | BadRetriever | PgVectorRetriever = BadRetriever(
            [catalog.by_id[DECOY_CHUNK_ID]]
        )
    else:
        retriever = _embedding_retriever(catalog, settings)
    if variant == "no_guardrail":
        return _pipeline(
            catalog, settings, variant, retriever, provider, "unguarded", UNGUARDED_SYSTEM
        )
    return _pipeline(catalog, settings, variant, retriever, provider, "guarded", GUARDED_SYSTEM)


def build_pgvector_pipeline(
    catalog: Catalog,
    settings: Settings,
    dsn: str,
    variant: str,
    provider: LLMProvider,
) -> Pipeline:
    _check_variant(variant)
    if variant == "no_guardrail":
        mode = "unguarded"
        prompt = UNGUARDED_SYSTEM
    else:
        mode = "guarded"
        prompt = GUARDED_SYSTEM
    if variant == "bad_retriever":
        retriever: EmbeddingRetriever | BadRetriever | PgVectorRetriever = BadRetriever(
            [catalog.by_id[DECOY_CHUNK_ID]]
        )
    else:
        embedder = HashingEmbedder(settings.embedding_dim)
        store = PgVectorIndex(connect(dsn), embedder, indexable_chunks(catalog.chunks))
        retriever = PgVectorRetriever(store)
    return _pipeline(catalog, settings, variant, retriever, provider, mode, prompt)


def snapshot_lines(comparison: Comparison) -> list[str]:
    if comparison.mode != "offline":
        raise ValueError("snapshots record the offline deterministic run")
    lines: list[str] = []
    for name in VARIANT_ORDER:
        variant = comparison.variants[name]
        for row in variant.rows:
            record = {
                "schema": "harborlight-pipeline-snapshot-v1",
                "variant": name,
                "id": row.id,
                "question": row.question,
                "response": row.response,
                "retrieved_ids": row.retrieved_ids,
                "shown_ids": row.shown_ids,
                "provider": variant.provider,
                "judge": {"status": "not_run", "reason": JUDGE_NOT_RUN_REASON},
            }
            lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return lines


def write_snapshot(path: Path, comparison: Comparison) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(snapshot_lines(comparison)) + "\n", encoding="utf-8")


def write_reports(
    comparison: Comparison, markdown_path: Path | None, html_path: Path | None
) -> None:
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(comparison), encoding="utf-8")
    if html_path is not None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_html(comparison), encoding="utf-8")


def format_summary(comparison: Comparison) -> str:
    lines = [
        f"mode={comparison.mode} variant={comparison.gated_variant} "
        f"passed={'yes' if comparison.passed else 'no'}"
    ]
    gated = comparison.variants[comparison.gated_variant]
    for metric in gated.metrics:
        lines.append(
            f"{metric.name}={metric.value:.3f} threshold={metric.threshold:.3f} "
            f"passed={'yes' if metric.passed else 'no'}"
        )
    return "\n".join(lines)


def _score_pipeline(
    pipeline: Pipeline,
    questions: list[EvalQuestion],
    catalog: Catalog,
    thresholds: dict[str, float],
) -> VariantEval:
    outputs = [pipeline.answer(question.question, question.id) for question in questions]
    chunk_text = {chunk.id: chunk.text for chunk in catalog.chunks}
    return score_outputs(
        questions,
        outputs,
        chunk_text,
        thresholds,
        pipeline.variant,
        pipeline.provider_name,
    )


def _embedding_retriever(catalog: Catalog, settings: Settings) -> EmbeddingRetriever:
    embedder = HashingEmbedder(settings.embedding_dim)
    index = FaissIndex(embedder, indexable_chunks(catalog.chunks))
    return EmbeddingRetriever(index)


def _pipeline(
    catalog: Catalog,
    settings: Settings,
    variant: str,
    retriever: EmbeddingRetriever | BadRetriever | PgVectorRetriever,
    provider: LLMProvider,
    mode: Any,
    prompt: str,
) -> Pipeline:
    return Pipeline(
        retriever=retriever,
        provider=provider,
        catalog=catalog,
        mode=mode,
        variant=variant,
        top_k=settings.top_k,
        system_prompt=prompt,
    )


def _live_provider(provider_name: str, settings: Settings) -> LLMProvider:
    if provider_name == "openai":
        from openai import OpenAI

        return OpenAIProvider(OpenAI(), settings.openai_chat_model)
    if provider_name == "anthropic":
        from anthropic import Anthropic

        key = os.environ.get("ANTHROPIC_API_KEY")
        return AnthropicProvider(Anthropic(api_key=key), settings.anthropic_model)
    raise ValueError(provider_name)


def _load_all() -> tuple[Catalog, list[EvalQuestion], Settings]:
    catalog = load_corpus(corpus_dir())
    questions = load_questions(questions_path(), catalog)
    return catalog, questions, load_settings()


def _check_variant(variant: str) -> None:
    if variant not in VARIANT_ORDER:
        raise ValueError(f"unknown variant {variant}")


def _mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a mapping")
    return loaded


def _int_field(raw: dict[str, Any], name: str, default: int) -> int:
    if name not in raw:
        return default
    value = raw[name]
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an int")
    return value


def _str_field(raw: dict[str, Any], name: str, default: str) -> str:
    if name not in raw:
        return default
    value = raw[name]
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _float_group(raw: dict[str, Any], group: str, names: tuple[str, ...]) -> dict[str, float]:
    section = raw.get(group)
    if not isinstance(section, dict):
        raise ValueError(f"thresholds.{group} must be a mapping")
    values: dict[str, float] = {}
    for name in names:
        if name not in section:
            raise ValueError(f"thresholds.{group}.{name} is missing")
        number = section[name]
        if isinstance(number, bool) or not isinstance(number, int | float):
            raise ValueError(f"thresholds.{group}.{name} must be a number")
        values[name] = float(number)
    return values
