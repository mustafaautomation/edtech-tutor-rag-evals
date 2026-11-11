"""Command line for asking a question and for running the eval gate."""

import argparse
import sys
from pathlib import Path

from harborlight_tutor.corpus import load_corpus
from harborlight_tutor.paths import corpus_dir
from harborlight_tutor.pipeline import VARIANT_ORDER
from harborlight_tutor.providers import DeterministicTutor
from harborlight_tutor.ragas_live import LiveEvalUnavailable
from harborlight_tutor.runner import (
    build_pgvector_pipeline,
    build_variant,
    format_summary,
    load_settings,
    run_live,
    run_offline,
    write_reports,
    write_snapshot,
)


def eval_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harborlight-eval")
    parser.add_argument("--mode", choices=["offline", "live"], required=True)
    parser.add_argument("--variant", choices=VARIANT_ORDER, default="improved")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--report-html", type=Path)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "offline":
            comparison = run_offline(args.variant)
        else:
            comparison = run_live(args.variant, args.provider)
    except LiveEvalUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(format_summary(comparison))
    write_reports(comparison, args.report_md, args.report_html)
    if args.snapshot is not None:
        if args.mode != "offline":
            print("snapshots are written from offline mode only", file=sys.stderr)
            return 2
        write_snapshot(args.snapshot, comparison)
    return 0 if comparison.passed else 1


def ask_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harborlight-ask")
    parser.add_argument("question")
    parser.add_argument("--variant", choices=VARIANT_ORDER, default="improved")
    parser.add_argument("--index", choices=["faiss", "pgvector"], default="faiss")
    parser.add_argument("--dsn", default="")
    parser.add_argument("--show-context", action="store_true")
    args = parser.parse_args(argv)
    catalog = load_corpus(corpus_dir())
    settings = load_settings()
    if args.variant == "no_guardrail":
        provider = DeterministicTutor("unguarded")
    else:
        provider = DeterministicTutor("guarded")
    if args.index == "pgvector":
        dsn = args.dsn or _env_dsn()
        if not dsn:
            print("pgvector needs --dsn or DATABASE_URL", file=sys.stderr)
            return 2
        pipeline = build_pgvector_pipeline(catalog, settings, dsn, args.variant, provider)
    else:
        pipeline = build_variant(catalog, settings, args.variant, provider)
    output = pipeline.answer(args.question)
    if args.show_context:
        for item in output.retrieved:
            print(f"{item.score:.3f} {item.chunk.id}", file=sys.stderr)
    print(output.response)
    return 0


def eval_entry() -> None:
    sys.exit(eval_main())


def ask_entry() -> None:
    sys.exit(ask_main())


def _env_dsn() -> str:
    import os

    return os.environ.get("DATABASE_URL", "")
