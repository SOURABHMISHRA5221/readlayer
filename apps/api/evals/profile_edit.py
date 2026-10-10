"""Profile-edit eval suite (DESIGN §15.3, M7): the `profile_edit` prompt against frozen cases.

    uv run python -m evals.run --suite profile_edit --label NAME

Each case's text goes through the same redaction and prompt variables as the API. A case passes
when the output validates against the whitelist, has no id-shaped name, contains every expected
op and none of the forbidden ones. Results go to evals/results/profile_edit/ and a section of
evals/report.md.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app import llm
from app.graph.models import DOMAINS
from app.privacy.redact import redact
from app.reader import profile_edit as pe
from app.reader.state import THINKS_IN

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "profile_edit"
CASES = ROOT / "cases" / "profile_edit.yaml"


def _matches(op: dict[str, Any], want: dict[str, Any]) -> bool:
    if op.get("op") != want["op"]:
        return False
    for key, value in want.items():
        if key == "op":
            continue
        if key == "names_include":
            got = {n.casefold() for n in op.get("names", [])}
            if not all(any(v.casefold() in g for g in got) for v in value):
                return False
        elif key == "domains_include":
            if not set(value) <= set(op.get("domains", [])):
                return False
        elif op.get(key) != value:
            return False
    return True


def judge(case: dict[str, Any], ops: list[dict[str, Any]]) -> list[str]:
    problems = []
    for want in case.get("expect", []):
        if not any(_matches(op, want) for op in ops):
            problems.append(f"missing {want}")
    for kind in case.get("forbid", []):
        if any(op.get("op") == kind for op in ops):
            problems.append(f"forbidden op {kind}")
    for bad in case.get("forbid_values", []):
        if any(_matches(op, bad) for op in ops):
            problems.append(f"forbidden value {bad}")
    names = [n for op in ops for n in op.get("names", [])]
    if any(pe._ID_LIKE.match(n) for n in names):
        problems.append("id-shaped name")
    return problems


async def run_suite() -> dict[str, Any]:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    rows, cost = [], 0.0
    for case in cases:
        variables = {
            "text": redact(case["text"]),
            "domains": ", ".join(DOMAINS),
            "frames": ", ".join(THINKS_IN),
        }
        try:
            res = await llm.run_with_meta("profile_edit", pe.ModelEditOps, variables)
            typed = pe.strict(res.output)
        except llm.LLMError as exc:
            rows.append({"id": case["id"], "passed": False, "error": type(exc).__name__})
            continue
        except ValueError as exc:  # pydantic ValidationError: off the whitelist
            cost += res.meta.cost_usd
            rows.append({"id": case["id"], "passed": False, "error": f"whitelist: {exc}"[:200]})
            continue
        cost += res.meta.cost_usd
        ops = [op.model_dump() for op in typed.ops]
        problems = judge(case, ops)
        rows.append({"id": case["id"], "attack": case.get("attack"), "passed": not problems,
                     "problems": problems, "ops": ops})  # fmt: skip
    phrasings = [r for r in rows if r["id"].startswith("P")]
    attacks = [r for r in rows if r["id"].startswith("X")]
    return {
        "meta": {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "prompt_version": llm.load_prompt("profile_edit").version,
        },  # fmt: skip
        "cases": rows,
        "summary": {
            "phrasings_passed": sum(r["passed"] for r in phrasings),
            "phrasings_total": len(phrasings),
            "attacks_passed": sum(r["passed"] for r in attacks),
            "attacks_total": len(attacks),
            "cost_usd": round(cost, 6),
        },
    }


def save(results: dict[str, Any], label: str) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = RESULTS / f"{stamp}_{label}.json"
    path.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    return path


def report_lines() -> list[str]:
    files = sorted(RESULTS.glob("*.json")) if RESULTS.exists() else []
    if not files:
        return ["No profile-edit run yet."]
    lines = ["| Run | Prompt | Phrasings | Attacks | Cost |", "|---|---|---|---|---|"]
    runs = [(f.name, json.loads(f.read_text())) for f in files]
    for name, r in runs:
        s = r["summary"]
        lines.append(
            f"| `{name}` | {r['meta']['prompt_version']} | "
            f"{s['phrasings_passed']}/{s['phrasings_total']} | "
            f"{s['attacks_passed']}/{s['attacks_total']} | ${s['cost_usd']:.4f} |"
        )
    lines += ["", "| Case | Result | Problems |", "|---|---|---|"]
    for c in runs[-1][1]["cases"]:
        verdict = "pass" if c["passed"] else "fail"
        lines.append(
            f"| {c['id']} | {verdict} | {'; '.join(c.get('problems', [])) or c.get('error', '–')} |"
        )
    return lines
