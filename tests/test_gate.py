import json

import pytest

from harborlight_tutor.cli import ask_main, eval_main
from harborlight_tutor.paths import repo_root, snapshot_path
from harborlight_tutor.report import render_html, render_markdown
from harborlight_tutor.runner import format_summary, snapshot_lines


def test_labelled_set_covers_guardrails(comparison) -> None:
    rows = comparison.variants["improved"].rows
    behaviors = {row.expected_behavior for row in rows}
    assert behaviors == {"answer", "hint", "refuse"}
    assert 30 <= len(rows) <= 50


def test_improved_variant_passes_the_gate(comparison) -> None:
    failed = [
        f"{row.id} retrieved={row.retrieved_ids} reasons={row.reasons} response={row.response}"
        for row in comparison.variants["improved"].rows
        if row.failed
    ]
    assert comparison.passed, format_summary(comparison) + "\n" + "\n".join(failed)


def test_bad_retriever_fails_the_gate(comparison) -> None:
    assert comparison.variants["bad_retriever"].passed is False
    assert comparison.variants["bad_retriever"].metric("hit_rate").value < 0.8


def test_no_guardrail_fails_and_leaks_a_solution(comparison) -> None:
    variant = comparison.variants["no_guardrail"]
    assert variant.passed is False
    assert variant.metric("refusal_correctness").value < 0.9
    leaked = [row for row in variant.rows if row.id == "q24"]
    assert leaked and "3.162" in leaked[0].response
    improved = comparison.variants["improved"]
    assert all("3.162" not in row.response for row in improved.rows)
    assert all("45.872" not in row.response for row in improved.rows)


def test_report_mentions_the_three_variants(comparison) -> None:
    markdown = render_markdown(comparison)
    html = render_html(comparison)
    for name in ("improved", "no_guardrail", "bad_retriever", "Before / after"):
        assert name in markdown
        assert name in html
    assert "not recorded here" in markdown or "not recorded" in markdown


def test_offline_cli_passes_and_bad_cli_fails() -> None:
    assert eval_main(["--mode", "offline", "--variant", "improved"]) == 0
    assert eval_main(["--mode", "offline", "--variant", "bad_retriever"]) == 1


def test_live_cli_without_a_key_does_not_invent_scores(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert eval_main(["--mode", "live", "--variant", "improved"]) == 2


def test_ask_quotes_the_mean(capsys: pytest.CaptureFixture[str]) -> None:
    assert ask_main(["What is the arithmetic mean of a sample?"]) == 0
    assert "sum of the values divided by the number of values" in capsys.readouterr().out


def test_committed_report_matches_this_code(comparison) -> None:
    root = repo_root()
    assert (root / "docs" / "example-report.md").read_text(encoding="utf-8") == render_markdown(
        comparison
    )
    assert (root / "docs" / "example-report.html").read_text(encoding="utf-8") == render_html(
        comparison
    )


def test_snapshot_has_no_judge_scores(comparison) -> None:
    saved = snapshot_path().read_text(encoding="utf-8").splitlines()
    assert saved == snapshot_lines(comparison)
    record = json.loads(saved[0])
    assert record["judge"]["status"] == "not_run"
    assert "live mode" in record["judge"]["reason"]
    assert "score" not in record["judge"]


def test_readme_quotes_the_offline_table() -> None:
    report = (repo_root() / "docs" / "example-report.md").read_text(encoding="utf-8")
    readme = (repo_root() / "README.md").read_text(encoding="utf-8")
    table = [
        line
        for line in report.splitlines()
        if line.startswith("| non_llm_context_recall |") or line.startswith("| mrr |")
        if "(pass)" in line or "(FAIL)" in line
    ]
    assert table
    for line in table:
        assert line in readme


def test_ragas_collections_api_imports() -> None:
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    assert Faithfulness.__name__ == "Faithfulness"
    assert AnswerRelevancy.__name__ == "AnswerRelevancy"
    assert ContextPrecisionWithReference.__name__ == "ContextPrecisionWithReference"
    assert ContextRecall.__name__ == "ContextRecall"
