"""Markdown and HTML reports for one eval comparison."""

import html
from dataclasses import dataclass

from harborlight_tutor.metrics import LIVE_METRICS, VariantEval
from harborlight_tutor.pipeline import VARIANT_ORDER


@dataclass
class Comparison:
    mode: str
    variants: dict[str, VariantEval]
    gated_variant: str
    notes: list[str]

    @property
    def passed(self) -> bool:
        return self.variants[self.gated_variant].passed


def render_markdown(comparison: Comparison) -> str:
    lines = [
        "# Harborlight STAT 101 tutor eval",
        "",
        f"Mode: `{comparison.mode}`. Gated variant: `{comparison.gated_variant}`. "
        f"Result: **{'pass' if comparison.passed else 'fail'}**.",
        "",
    ]
    for note in comparison.notes:
        lines.append(f"- {note}")
    lines.extend(["", "## Metric table", ""])
    names = _metric_names(comparison)
    header = ["metric", "threshold", *list(_present(comparison))]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for name in names:
        threshold = _threshold(comparison, name)
        cells = [name, f"{threshold:.3f}"]
        for variant in _present(comparison):
            metric = comparison.variants[variant].metric(name)
            mark = "pass" if metric.passed else "FAIL"
            cells.append(f"{metric.value:.3f} ({mark})")
        lines.append("| " + " | ".join(cells) + " |")
    if _has_baseline(comparison):
        lines.extend(["", "## Before / after", ""])
        lines.append(
            "improved is the guarded tutor. no_guardrail uses the same retriever but returns "
            "graded solutions and an unsourced claim. bad_retriever keeps the guarded tutor and "
            "returns an unrelated note."
        )
        lines.append("")
        lines.append("| metric | improved − no_guardrail | improved − bad_retriever |")
        lines.append("| --- | --- | --- |")
        for name in names:
            if name in LIVE_METRICS:
                continue
            improved = comparison.variants["improved"].metric(name).value
            bare = comparison.variants["no_guardrail"].metric(name).value
            bad = comparison.variants["bad_retriever"].metric(name).value
            lines.append(f"| {name} | {improved - bare:+.3f} | {improved - bad:+.3f} |")
    for variant in _present(comparison):
        failed = [row for row in comparison.variants[variant].rows if row.failed]
        lines.extend(["", f"## Failures: {variant}", ""])
        if not failed:
            lines.append("None.")
            continue
        for row in failed:
            lines.append(f"### {row.id}")
            lines.append("")
            lines.append(f"- Question: {_cell(row.question)}")
            lines.append(f"- Expected: {row.expected_behavior}")
            lines.append(f"- Retrieved: {', '.join(row.retrieved_ids) or '(none)'}")
            lines.append(f"- Reasons: {_cell('; '.join(row.reasons) or 'n/a')}")
            lines.append(f"- Response: {_cell(row.response)}")
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def render_html(comparison: Comparison) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Harborlight STAT 101 tutor eval</title>",
        "<style>",
        "body{font-family:Georgia,serif;max-width:960px;margin:2rem auto;"
        "padding:0 1rem;color:#1c1917;}",
        "table{border-collapse:collapse;width:100%;margin:1rem 0;}",
        "th,td{border:1px solid #d6d3d1;padding:0.4rem 0.6rem;text-align:left;vertical-align:top;}",
        "th{background:#f5f5f4;}",
        ".pass{color:#166534;}",
        ".fail{color:#991b1b;font-weight:600;}",
        "h1{font-size:1.6rem;} h2{font-size:1.2rem;margin-top:1.6rem;}",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Harborlight STAT 101 tutor eval</h1>",
        f"<p>Mode: {html.escape(comparison.mode)}. "
        f"Gated variant: {html.escape(comparison.gated_variant)}. "
        f'Result: <strong class="{"pass" if comparison.passed else "fail"}">'
        f"{'pass' if comparison.passed else 'fail'}</strong>.</p>",
        "<ul>",
    ]
    for note in comparison.notes:
        parts.append(f"<li>{html.escape(note)}</li>")
    parts.extend(["</ul>", "<h2>Metric table</h2>", "<table>", "<thead><tr>"])
    for column in ["metric", "threshold", *_present(comparison)]:
        parts.append(f"<th>{html.escape(column)}</th>")
    parts.append("</tr></thead><tbody>")
    for name in _metric_names(comparison):
        parts.append("<tr>")
        parts.append(f"<td>{html.escape(name)}</td>")
        parts.append(f"<td>{_threshold(comparison, name):.3f}</td>")
        for variant in _present(comparison):
            metric = comparison.variants[variant].metric(name)
            css = "pass" if metric.passed else "fail"
            parts.append(f'<td class="{css}">{metric.value:.3f}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table>")
    if _has_baseline(comparison):
        parts.extend(
            [
                "<h2>Before / after</h2>",
                "<p>improved is the guarded tutor. no_guardrail uses the same retriever but "
                "returns graded solutions and an unsourced claim. bad_retriever keeps the "
                "guarded tutor and returns an unrelated note.</p>",
                "<table><thead><tr><th>metric</th><th>improved − no_guardrail</th>"
                "<th>improved − bad_retriever</th></tr></thead><tbody>",
            ]
        )
        for name in _metric_names(comparison):
            if name in LIVE_METRICS:
                continue
            improved = comparison.variants["improved"].metric(name).value
            bare = comparison.variants["no_guardrail"].metric(name).value
            bad = comparison.variants["bad_retriever"].metric(name).value
            parts.append(
                "<tr>"
                f"<td>{html.escape(name)}</td>"
                f"<td>{improved - bare:+.3f}</td>"
                f"<td>{improved - bad:+.3f}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    for variant in _present(comparison):
        failed = [row for row in comparison.variants[variant].rows if row.failed]
        parts.append(f"<h2>Failures: {html.escape(variant)}</h2>")
        if not failed:
            parts.append("<p>None.</p>")
            continue
        for row in failed:
            parts.append(f"<h3>{html.escape(row.id)}</h3>")
            parts.append("<ul>")
            parts.append(f"<li>Question: {html.escape(row.question)}</li>")
            parts.append(f"<li>Expected: {html.escape(row.expected_behavior)}</li>")
            parts.append(
                "<li>Retrieved: " + html.escape(", ".join(row.retrieved_ids) or "(none)") + "</li>"
            )
            parts.append("<li>Reasons: " + html.escape("; ".join(row.reasons) or "n/a") + "</li>")
            parts.append(f"<li>Response: {html.escape(row.response)}</li>")
            parts.append("</ul>")
    parts.extend(["</body>", "</html>", ""])
    return "\n".join(parts)


def _present(comparison: Comparison) -> list[str]:
    return [name for name in VARIANT_ORDER if name in comparison.variants]


def _has_baseline(comparison: Comparison) -> bool:
    return set(VARIANT_ORDER).issubset(comparison.variants)


def _metric_names(comparison: Comparison) -> list[str]:
    gated = comparison.variants[comparison.gated_variant]
    return [metric.name for metric in gated.metrics]


def _threshold(comparison: Comparison, name: str) -> float:
    return comparison.variants[comparison.gated_variant].metric(name).threshold


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "/")
