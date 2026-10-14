"""M9 part 3 (E1, T1–T6): cost, cache and latency from production, read only.

    uv run python -m scripts.eval_ops            # after `make check-gcp`

Reads Firestore with field masks (no article or generated text enters this script) and Cloud
Logging for the last LOG_DAYS days, and writes `evals/ops_report.md` with aggregates only. Never
imports `app.llm`, never calls a model, never writes to Firestore.
"""

import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

EVALS = Path(__file__).resolve().parents[1] / "evals"
PROMPTS = Path(__file__).resolve().parents[1] / "app" / "prompts"
LOG_DAYS = 7
SERVICE = "readlayer-api"
# Growth's own calls. Its confirm step shares `link_confirm` with linking, so it counts as analysis.
GROWTH_TASKS = {"concept_define", "link_merge", "concept_prereqs"}
TRANSCRIBE_TASK = "transcribe"
CONTENT_FIELDS = ["source", "llm_calls", "media.kind", "media.transcript.cost_usd"]
EXPLAIN_FIELDS = ["part", "kind", "cost_usd", "prompt_version"]


# ---------------------------------------------------------------- pure parts (tested)


def percentile(xs: list[float], q: float) -> float:
    """Nearest-rank percentile; 0.0 for no samples."""
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))
    return s[k]


def summary(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {"n": 0, "median": 0.0, "mean": 0.0, "p90": 0.0}
    return {"n": len(xs), "median": median(xs), "mean": mean(xs), "p90": percentile(xs, 0.9)}


def article_costs(docs: Iterable[Mapping]) -> dict[str, dict[str, list[float]]]:
    """Per source (media docs as "media"): analysis cost (growth and transcript calls out),
    growth cost, transcript cost (from media.transcript.cost_usd only, counted once)."""
    out: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"analysis": [], "growth": [], "transcript": []}
    )
    for d in docs:
        media = d.get("media") or {}
        group = "media" if media.get("kind") else str(d.get("source", "unknown"))
        calls = d.get("llm_calls") or []
        skip = GROWTH_TASKS | {TRANSCRIBE_TASK}
        analysis = sum(c.get("cost_usd", 0.0) for c in calls if c.get("task") not in skip)
        growth = sum(c.get("cost_usd", 0.0) for c in calls if c.get("task") in GROWTH_TASKS)
        out[group]["analysis"].append(analysis)
        out[group]["growth"].append(growth)
        if media.get("kind"):
            out[group]["transcript"].append(
                float((media.get("transcript") or {}).get("cost_usd", 0.0))
            )
    return dict(out)


def explain_costs(entries: Iterable[Mapping], current: Mapping[str, str]) -> dict[str, list[float]]:
    """Cost per explanation part on the current prompt versions; definition-only outcomes apart.
    `current`: part → prompt version string as the cache records it."""
    out: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        part = e.get("part")
        if part not in current or e.get("prompt_version") != current[part]:
            continue
        key = part if e.get("kind") == "verified" else f"{part} (definition-only)"
        out[key].append(float(e.get("cost_usd", 0.0)))
    return dict(out)


def ratio(hits: int, misses: int) -> float | None:
    return hits / (hits + misses) if hits + misses else None


def seconds(latency: str | None) -> float | None:
    """Cloud Run's httpRequest.latency, e.g. "0.123456s"."""
    if not latency or not latency.endswith("s"):
        return None
    try:
        return float(latency[:-1])
    except ValueError:
        return None


def prompt_version(task: str, root: Path = PROMPTS) -> str:
    m = re.search(r"^version:\s*(\S+)", (root / f"{task}.md").read_text(), re.M)
    return m.group(1) if m else ""


def money(x: float) -> str:
    return f"${x:.4f}"


def report(data: Mapping) -> str:
    lines = [
        "# Cost, cache and latency (M9 part 3)",
        "",
        f"Generated {data['generated']} by `scripts/eval_ops.py` from production, read only: "
        "Firestore (field masks) and Cloud Logging. Costs cover everything stored to date; "
        f"cache and latency cover the last {LOG_DAYS} days of logs ({data['window']}). "
        "Aggregates only. Minimum instances is 0, so request latencies include cold starts.",
        "",
        "## Cost per article (model calls stored with each page)",
        "",
        f"All {data['pages_total']} pages stored to date. "
        "Analysis: demand extraction and linking (growth's confirm step shares the linker's "
        "`link_confirm` task, so it counts here). Growth: concept_define, link_merge, "
        "concept_prereqs. Transcript: a recording's transcription, once.",
        "",
        "| pages | n | analysis median / mean / p90 | growth median / mean | transcript mean |",
        "|---|---|---|---|---|",
    ]
    names = {"fetch": "library (corpus)", "user_ingested": "opened by readers",
             "extension": "extension", "media": "videos and podcasts"}  # fmt: skip
    for group, c in sorted(data["articles"].items()):
        a, g = summary(c["analysis"]), summary(c["growth"])
        t = summary(c["transcript"])
        tr = money(t["mean"]) if t["n"] else "—"
        cost = f"{money(a['median'])} / {money(a['mean'])} / {money(a['p90'])}"
        lines.append(
            f"| {names.get(group, group)} | {a['n']} | {cost} | "
            f"{money(g['median'])} / {money(g['mean'])} | {tr} |"
        )
    lines += ["", "## Cost per explanation part (current prompt versions)", "",
              f"Every cache entry on the current prompt versions, of {data['explain_total']} "
              "cache entries read.", "",
              "| part | n | median | mean |", "|---|---|---|---|"]  # fmt: skip
    for part, xs in sorted(data["explain"].items()):
        s = summary(xs)
        lines.append(f"| {part} | {s['n']} | {money(s['median'])} | {money(s['mean'])} |")
    lines += [
        "",
        "The restatement is made once per span and shared by every reader; the Background once per "
        "span, band, analogy domain and style. A card's cost to a reader is therefore usually a "
        "cache hit, not the sum of the two.",
        "",
        "## Cache",
        "",
        "| cache | hits | generated / ingested | hit rate | source |",
        "|---|---|---|---|---|",
    ]
    for name, (hits, misses, source) in data["caches"].items():
        r = ratio(hits, misses)
        rate = f"{r:.0%}" if r is not None else "—"
        lines.append(f"| {name} | {hits} | {misses} | {rate} | {source} |")
    lines += [
        "",
        f"Web search: {data['search_calls'][0]} provider calls ({data['search_calls'][1]}; "
        "cache misses, no hit counter exists).",
        "",
        "## Latency",
        "",
        "| what | n | p50 | p95 | source |",
        "|---|---|---|---|---|",
    ]
    for name, (xs, source) in data["latency"].items():
        lines.append(f"| {name} | {len(xs)} | {percentile(xs, 0.5):.0f} ms | "
                     f"{percentile(xs, 0.95):.0f} ms | {source} |")  # fmt: skip
    lines += [
        "",
        "Latest values the API logs from its own rolling windows (in-process, per "
        "instance; not request latency):",
        "",
        "| window | values |",
        "|---|---|",
    ]
    for name, vals in data["rolling"].items():
        shown = ", ".join(f"{k.replace('_ms', '')} {v:.1f} ms" for k, v in vals.items())
        lines.append(f"| {name} | {shown or 'none logged'} |")
    total = sum(data["spend"].values())
    recent = sorted(data["spend"].items())[-14:]
    lines += [
        "",
        "## Model spend on the project ledger",
        "",
        "All model spend recorded in `ops/spend/days` (readers, plus local evals, seeding and warm "
        f"runs on production credentials). **Total to date: {money(total)} over "
        f"{len(data['spend'])} days.**",
        "",
        "| day (UTC) | spend |",
        "|---|---|",
    ] + [f"| {day} | {money(v)} |" for day, v in recent]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- reads (production)


def _logs(log_filter: str) -> list[dict]:
    """`gcloud logging read`, read only."""
    out = subprocess.run(
        ["gcloud", "logging", "read", log_filter, "--format=json", f"--freshness={LOG_DAYS}d",
         "--limit=20000"],  # fmt: skip
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout or "[]")


def in_window(days: Mapping[str, Mapping], start: str) -> tuple[list[str], str]:
    """Day docs dated on or after the window start (ledger days can be missing), and their range."""
    picked = sorted(d for d in days if d >= start)
    return picked, (f"{picked[0]} to {picked[-1]}" if picked else "no days")


def latest(entries: list[dict], fields: Iterable[str]) -> dict[str, float]:
    """The newest log entry's numeric fields (the rolling windows the API logs itself)."""
    if not entries:
        return {}
    p = max(entries, key=lambda e: e.get("timestamp", "")).get("jsonPayload") or {}
    return {f: float(p[f]) for f in fields if isinstance(p.get(f), (int, float))}


def with_samples(fields: Mapping[str, float]) -> dict[str, float]:
    """Drop a class whose rolling window was empty (its percentiles read 0), and the counts."""
    empty = {k[: -len("_n")] for k, v in fields.items() if k.endswith("_n") and not v}
    return {
        k: v for k, v in fields.items()
        if not k.endswith("_n") and not any(k.startswith(e + "_") for e in empty)
    }  # fmt: skip


def collect(db, logs=_logs) -> dict:  # noqa: ANN001 (a Firestore client or a fake)
    contents = [s.to_dict() for s in db.collection("contents").select(CONTENT_FIELDS).stream()]
    explanations = [
        s.to_dict() for s in db.collection("explanations").select(EXPLAIN_FIELDS).stream()
    ]
    explain_days = {s.id: s.to_dict() for s in db.collection("ops/explain/days").stream()}
    spend_days = {s.id: s.to_dict() for s in db.collection("ops/spend/days").stream()}
    search_days = {s.id: s.to_dict() for s in db.collection("ops/search/days").stream()}
    current = {
        "restatement": f"{prompt_version('restate')}+{prompt_version('verify')}",
        "background": f"{prompt_version('explain')}+{prompt_version('verify_background')}",
    }
    run = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{SERVICE}"'
    explain_lines = logs(f'{run} AND jsonPayload.message="explain"')
    # GET only: the browser's CORS preflight (OPTIONS) hits the same path and answers in ms.
    annotate = logs(
        f'{run} AND httpRequest.requestUrl:"/annotations" AND httpRequest.status=200 '
        'AND httpRequest.requestMethod="GET"'
    )
    opened = logs(f'{run} AND jsonPayload.message="rec opened"')
    cache_hit = logs(f'{run} AND jsonPayload.message="content cache hit"')
    ingested = logs(f'{run} AND jsonPayload.message="content ingested"')
    scoring = logs(f'{run} AND jsonPayload.message="annotation scoring latency"')
    rolling = logs(f'{run} AND jsonPayload.message="explanation latency"')
    stamps = sorted(
        e.get("timestamp", "") for e in [*explain_lines, *annotate] if e.get("timestamp")
    )
    start = stamps[0][:10] if stamps else datetime.now(UTC).strftime("%Y-%m-%d")
    explain_in, explain_range = in_window(explain_days, start)
    search_in, search_range = in_window(search_days, start)
    hits = sum(int(explain_days[d].get("hits", 0)) for d in explain_in)
    generated = sum(int(explain_days[d].get("generated", 0)) for d in explain_in)
    reused = sum(1 for e in opened if (e.get("jsonPayload") or {}).get("new") is False)
    fresh = sum(1 for e in opened if (e.get("jsonPayload") or {}).get("new") is True)
    lat = defaultdict(list)
    for e in explain_lines:
        p = e.get("jsonPayload") or {}
        if not isinstance(p.get("latency_ms"), (int, float)) or p.get("reason") == "capped":
            continue  # capped requests answer at once with no explanation
        kind = "cached" if p.get("cache") == "hit" else "generated"
        lat[f"explanation request, {kind}"].append(float(p["latency_ms"]))
    annotate_ms = [
        s * 1000
        for e in annotate
        if (s := seconds((e.get("httpRequest") or {}).get("latency"))) is not None
    ]
    explain_source = "`explain` log line `latency_ms`, capped requests left out"
    return {
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "window": f"{stamps[0][:10]} to {stamps[-1][:10]}" if stamps else "no log entries",
        "articles": article_costs(contents),
        "pages_total": len(contents),
        "explain": explain_costs(explanations, current),
        "explain_total": len(explanations),
        "caches": {
            "explanations": (hits, generated, f"`ops/explain/days`, {explain_range}"),
            "pages opened (Open here, Read any link)": (
                reused,
                fresh,
                "`rec opened` log lines: already stored vs fetched new",
            ),
            "pages ingested (every ingest path)": (
                len(cache_hit),
                len(ingested),
                "`content cache hit` / `content ingested` log lines",
            ),
        },  # fmt: skip
        "search_calls": (sum(int(search_days[d].get("calls", 0)) for d in search_in), search_range),
        "latency": {
            "annotations route, GET (request)": (annotate_ms, "Cloud Run request logs, 200, GET"),
            **{k: (v, explain_source) for k, v in sorted(lat.items())},
        },
        "rolling": {
            "annotation scoring (in-process, last 200)": latest(scoring, ["p95_ms"]),
            "explanation (in-process windows)": with_samples(
                latest(
                    rolling,
                    [
                        f"{k}_{f}"
                        for k in ("cached", "generated")
                        for f in ("p50_ms", "p95_ms", "n")
                    ],
                )
            ),  # fmt: skip
        },
        "spend": {d: float(v.get("cost_usd", 0.0)) for d, v in spend_days.items()},
    }


def main() -> int:
    from google.cloud import firestore

    from app.config import get_settings

    db = firestore.Client(project=get_settings().db_project or None)
    out = report(collect(db))
    (EVALS / "ops_report.md").write_text(out, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
