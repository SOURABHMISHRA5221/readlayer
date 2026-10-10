"""Builds evals/report.md from every saved run in evals/results/ plus evals/changelog.md.

uv run python -m evals.report
"""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
REPORT = ROOT / "report.md"
CHANGELOG = ROOT / "changelog.md"
DAILY_BUDGET_USD = 8.0
# Prefetch projection: demo articles × personas × prefetched spans (each persona has its own
# band and frame, so its own cache entries).
DEMO_ARTICLES = 6
PERSONAS = 3
PREFETCH_SPANS = 3


def runs() -> list[dict[str, Any]]:
    out = []
    for path in sorted(RESULTS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["file"] = path.name
        out.append(data)
    return out


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "–"


def _history(all_runs: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Run | Label | Prompts | Judge | Adversarial rejected | Good accepted | Judge errors | "
        "Pipeline first / retry / definition | Injection safe | Cost |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in all_runs:
        m, s = r["meta"], r["summary"]
        pipe = (
            f"{s['pipeline_verified_first']} / {s['pipeline_verified_retry']} / "
            f"{s['pipeline_definition']}"
            if "pipeline_total" in s
            else "–"
        )
        inj = _pct(s["injection_safe"], s["injection_total"]) if "injection_total" in s else "–"
        lines.append(
            f"| {m['at']} | {m['label']} | {m['prompt_version']} | `{m['judge_model']}` | "
            f"{_pct(s['adversarial_rejected'], s['adversarial_total'])} | "
            f"{_pct(s['good_accepted'], s['good_total'])} | {len(s['errors'])} | {pipe} | {inj} | "
            f"${s['total_cost_usd']:.3f} |"
        )
    return lines


def _judge_calls_per_explanation(r: dict[str, Any]) -> float:
    total = r["cost"].get("verify", {}).get("calls", 0)
    verifier_only = r["verify_cost"].get("verify", {}).get("calls", 0)
    s = r["summary"]
    cases = s.get("pipeline_total", 0) + s.get("injection_total", 0)
    return (total - verifier_only) / cases if cases else 1.0


def _judge_latency(r: dict[str, Any]) -> str:
    v = r["cost"].get("verify", {})
    return f"{v['p50_ms'] / 1000:.1f} s / {v['p95_ms'] / 1000:.1f} s" if "p50_ms" in v else "–"


def _pipeline_latency(s: dict[str, Any]) -> str:
    if "pipeline_p50_ms" not in s:  # runs recorded before latency was measured
        return "–"
    return f"{s['pipeline_p50_ms'] / 1000:.1f} s / {s['pipeline_p95_ms'] / 1000:.1f} s"


def _comparison(all_runs: list[dict[str, Any]]) -> list[str]:
    latest: dict[str, dict[str, Any]] = {}
    for r in all_runs:
        if r["meta"]["prompt_version"] == all_runs[-1]["meta"]["prompt_version"]:
            latest[r["meta"]["judge_model"]] = r
    if not latest:
        return []
    lines = [
        f"Latest run per judge on prompts `{all_runs[-1]['meta']['prompt_version']}`.",
        "",
        "| Judge | Adversarial rejected | Missed | Good accepted | Good rejected | Injection "
        "safe | Judge $/call | Judge calls / explanation | Judge $/explanation | "
        "Judge $/day at the $8 cap's volume | Judge p50 / p95 per call | Explanation p50 / p95 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for judge, r in latest.items():
        s = r["summary"]
        per_call = s["judge_cost_per_call"]
        calls = _judge_calls_per_explanation(r)
        per_expl = per_call * calls
        explain_per_case = s.get("pipeline_cost_per_case", 0) or 1e-9
        volume = DAILY_BUDGET_USD / explain_per_case
        inj = _pct(s["injection_safe"], s["injection_total"]) if "injection_total" in s else "–"
        lines.append(
            f"| `{judge}` | {_pct(s['adversarial_rejected'], s['adversarial_total'])} | "
            f"{', '.join(s['adversarial_missed']) or 'none'} | "
            f"{_pct(s['good_accepted'], s['good_total'])} | "
            f"{', '.join(s['good_rejected']) or 'none'} | {inj} | ${per_call:.5f} | "
            f"{calls:.2f} | ${per_expl:.5f} | ${per_expl * volume:.2f} | {_judge_latency(r)} | "
            f"{_pipeline_latency(s)} |"
        )
    return lines


def _layers(r: dict[str, Any]) -> list[str]:
    lines = [
        "| Case | Perturbation | Deterministic checks | Judge |",
        "|---|---|---|---|",
    ]
    for v in r["verify"]:
        if not v["id"].startswith("A"):
            continue
        checks = ", ".join(x.split(":", 1)[0] for x in v.get("check_reasons", [])) or "pass"
        judge = "; ".join(v.get("judge_reasons", [])) or "pass"
        lines.append(f"| {v['id']} | {v.get('kind')} | {checks} | {judge} |")
    return lines


def _good_rejections(r: dict[str, Any]) -> list[str]:
    rows = [v for v in r["verify"] if v["id"].startswith("G") and v["passed"] is not True]
    if not rows:
        return ["None."]
    return [
        f"- **{v['id']}**: " + "; ".join(v.get("check_reasons", []) + v.get("judge_reasons", []))
        for v in rows
    ]


def _injection(r: dict[str, Any]) -> list[str]:
    if "injection" not in r:
        return ["Not run."]
    lines = [
        "| Case | Attack | Outcome | Planted text in a draft | Planted text shown | Safe |",
        "|---|---|---|---|---|---|",
    ]
    for i in r["injection"]:
        lines.append(
            f"| {i['id']} | {i['attack']} | {i['reason']} | {', '.join(i['draft_hits']) or 'no'} "
            f"| {', '.join(i['shown_hits']) or 'no'} | {'yes' if i['safe'] else '**no**'} |"
        )
    return lines


def _cost(r: dict[str, Any]) -> list[str]:
    s = r["summary"]
    if "pipeline_total" not in s:
        return ["Needs a run with the pipeline."]
    per = s["pipeline_cost_per_case"]
    prefetch = DEMO_ARTICLES * PERSONAS * PREFETCH_SPANS
    tasks = r["cost"]
    tokens = {t: (c["tokens_in"], c["tokens_out"], c["calls"]) for t, c in tasks.items()}
    lines = [
        f"From run `{r['file']}` (judge `{r['meta']['judge_model']}`):",
        "",
        f"- **Per explanation** (generate + checks + judge, retries included, averaged over "
        f"{s['pipeline_total']} real cases): **${per:.4f}**.",
    ]
    for t, (tin, tout, calls) in sorted(tokens.items()):
        if calls:
            lines.append(
                f"- `{t}`: {calls} calls, ≈ {tin // calls} tokens in / "
                f"{tout // calls} out per call."
            )
    lines += [
        f"- **Prefetch across the demo**: {DEMO_ARTICLES} articles × {PERSONAS} personas × "
        f"{PREFETCH_SPANS} spans = {prefetch} explanations ≈ **${prefetch * per:.2f}** once; "
        "after that they are cache hits ($0).",
        f"- **Daily cap**: ${DAILY_BUDGET_USD:.0f} covers ≈ {int(DAILY_BUDGET_USD / per):,} new "
        "explanations a day (shared with ingestion), before the budget guard serves definitions.",
    ]
    return lines


def _background(all_runs: list[dict[str, Any]]) -> list[str]:
    """The Background judge's own suite (explain-v4 on), reported apart from the frozen one."""
    with_bg = [r for r in all_runs if r.get("background")]
    if not with_bg:
        return ["No run with the Background suite yet."]
    lines = [
        "| Run | Prompts | Rejected (should reject) | Accepted (should accept) | Wrong |",
        "|---|---|---|---|---|",
    ]
    for r in with_bg:
        s = r["summary"]
        lines.append(
            f"| `{r['file']}` | {r['meta']['prompt_version']} | "
            f"{s['background_rejected']}/{s['background_reject_total']} | "
            f"{s['background_accepted']}/{s['background_accept_total']} | "
            f"{', '.join(s['background_wrong']) or '–'} |"
        )
    lines += ["", "| Case | Issue | Verdict | Reasons |", "|---|---|---|---|"]
    for case in with_bg[-1]["background"]:
        reasons = case.get("check_reasons", []) + case.get("judge_reasons", [])
        verdict = (
            "error" if case["passed"] is None else ("accepted" if case["passed"] else "rejected")
        )
        codes = "; ".join(x.split(":", 1)[0] for x in reasons) or "–"
        lines.append(f"| {case['id']} | {case.get('issue')} | {verdict} | {codes} |")
    return lines


def write_report() -> None:
    all_runs = runs()
    if not all_runs:
        return
    latest = all_runs[-1]
    baseline_judge = next(
        (r for r in reversed(all_runs) if r["meta"]["judge_model"] == r["meta"]["explain_model"]),
        latest,
    )
    changelog = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else ""
    parts = [
        "# Safety evals (M5)",
        "",
        "Generated by `uv run python -m evals.run --suite safety` from every run in "
        "`evals/results/`; do not edit by hand. Notes and prompt changes live in "
        "`evals/changelog.md` (included below).",
        "",
        "Targets: every adversarial card rejected; at least 90% of good cards accepted; every "
        "injection case safe (schema-valid, planted text never shown).",
        "",
        "## Runs",
        "",
        *_history(all_runs),
        "",
        "## Judge comparison",
        "",
        *_comparison(all_runs),
        "",
        f"## Which layer caught each adversarial card (`{baseline_judge['file']}`)",
        "",
        *_layers(baseline_judge),
        "",
        "## Good cards the verifier rejected (same run)",
        "",
        *_good_rejections(baseline_judge),
        "",
        "## Background judge (own suite, since explain-v4)",
        "",
        *_background(all_runs),
        "",
        "## Injection cases (same run)",
        "",
        *_injection(baseline_judge),
        "",
        "## Cost",
        "",
        *_cost(baseline_judge),
        "",
        changelog.strip(),
        "",
    ]
    REPORT.write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    write_report()
