"""Render an evaluation report as Markdown."""

from __future__ import annotations

from datetime import datetime, timezone


def _check_line(c: dict) -> str:
    return f"- {'✅' if c['passed'] else '❌'} {c['name']}"


def render_markdown(report: dict) -> str:
    r = report["retrieval"]
    s = report["safety"]
    m = report["marking"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines = [
        "# Study Copilot — Evaluation Report",
        "",
        f"_Generated {now}_",
        "",
        "## Retrieval",
        "",
        f"- Queries: **{r['count']}**, k = {r['k']}, "
        f"retrieval = {'hybrid' if r['used_vector'] else 'keyword-only'}",
        f"- Recall@{r['k']} (any keyword): **{r['recall_any_at_k']}**",
        f"- Recall@{r['k']} (all keywords): **{r['recall_all_at_k']}**",
        f"- MRR: **{r['mrr']}**",
        "",
        "| Query | any | all | first rank | top result |",
        "|-------|-----|-----|-----------|------------|",
    ]
    for q in r["queries"]:
        lines.append(
            f"| {q['query']} | {'✓' if q['any_hit'] else '·'} "
            f"| {'✓' if q['all_hit'] else '·'} | {q['first_rank'] or '—'} "
            f"| {q['top_title'] or '—'} |"
        )

    lines += [
        "",
        f"## Safety ({s['passed']}/{s['total']} passed)",
        "",
        *[_check_line(c) for c in s["checks"]],
        "",
        f"## Marking consistency ({m['passed']}/{m['total']} passed)",
        "",
        *[_check_line(c) for c in m["checks"]],
        "",
    ]
    return "\n".join(lines) + "\n"
