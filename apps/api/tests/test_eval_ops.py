"""M9 part 3: the ops report's arithmetic, its read-only reads, and that it publishes no ids."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import eval_ops

API = Path(__file__).resolve().parents[1]
PRIVATE = re.compile(r"https?://|\b[0-9a-f]{32}\b|\b[0-9a-f]{16}\b|@")


def test_percentiles_and_summary():
    assert eval_ops.percentile([], 0.95) == 0.0
    assert eval_ops.percentile([10, 20, 30, 40], 0.5) == 20
    assert eval_ops.percentile(list(range(1, 101)), 0.95) == 95
    assert eval_ops.summary([1.0, 3.0])["median"] == 2.0 and eval_ops.summary([])["n"] == 0
    assert eval_ops.ratio(0, 0) is None and eval_ops.ratio(3, 1) == 0.75
    assert eval_ops.seconds("0.25s") == 0.25 and eval_ops.seconds(None) is None


def test_article_costs_split_growth_and_count_a_transcript_once():
    docs = [
        {"source": "fetch", "llm_calls": [{"task": "extract_demands", "cost_usd": 0.01},
                                          {"task": "concept_define", "cost_usd": 0.004}]},
        {"source": "user_ingested", "media": {"kind": "youtube", "transcript": {"cost_usd": 0.04}},
         "llm_calls": [{"task": "transcribe", "cost_usd": 0.04},
                       {"task": "extract_demands", "cost_usd": 0.02}]},
    ]  # fmt: skip
    got = eval_ops.article_costs(docs)
    assert got["fetch"] == {"analysis": [0.01], "growth": [0.004], "transcript": []}
    assert got["media"]["analysis"] == [0.02] and got["media"]["transcript"] == [0.04]


def test_explain_costs_use_current_versions_and_keep_definition_only_apart():
    current = {"restatement": "restate-v2+verify-v2", "background": "explain-v5+vb-v1"}

    def entry(part, kind, cost, version):
        return {"part": part, "kind": kind, "cost_usd": cost, "prompt_version": version}

    entries = [
        entry("restatement", "verified", 0.003, current["restatement"]),
        entry("restatement", "verified", 0.9, "restate-v1+verify-v1"),  # an old version
        entry("background", "definition", 0.005, current["background"]),
    ]
    assert eval_ops.explain_costs(entries, current) == {
        "restatement": [0.003],
        "background (definition-only)": [0.005],
    }


def test_prompt_versions_are_read_from_the_prompt_files():
    assert eval_ops.prompt_version("restate").startswith("restate-v")


class Snap:
    def __init__(self, doc_id, data):
        self.id, self._data = doc_id, data

    def to_dict(self):
        return dict(self._data)


class ReadOnlyCollection:
    def __init__(self, rows):
        self.rows = rows

    def select(self, fields):
        return self

    def stream(self):
        return [Snap(i, d) for i, d in self.rows.items()]

    def document(self, *a):
        raise AssertionError("no document access: reads go through select / stream")


class ReadOnlyClient:
    """Raises on anything but reading a collection."""

    def __init__(self, data):
        self.data = data

    def collection(self, path):
        return ReadOnlyCollection(self.data.get(path, {}))

    def __getattr__(self, name):  # batch, transaction, set, update, delete...
        raise AssertionError(f"write path used: {name}")


def test_collect_reads_only_and_the_report_publishes_no_ids():
    cid = "a" * 32
    data = {
        "contents": {
            cid: {"source": "fetch", "llm_calls": [{"task": "extract_demands", "cost_usd": 0.01}]}
        },
        "explanations": {"k1": {"part": "restatement", "kind": "verified", "cost_usd": 0.003,
                                "prompt_version": "x"}},
        "ops/explain/days": {"2026-10-14": {"hits": 30, "generated": 10}},
        "ops/spend/days": {"2026-10-13": {"cost_usd": 1.5}, "2026-10-14": {"cost_usd": 0.5}},
        "ops/search/days": {"2026-10-14": {"calls": 12}},
    }  # fmt: skip

    def logs(query):
        if "/annotations" in query:
            assert 'requestMethod="GET"' in query  # no CORS preflight (OPTIONS) in the p95
        if 'message="explain"' in query:
            return [
                {"timestamp": "2026-10-14T01:00:00Z",
                 "jsonPayload": {"cache": "hit", "latency_ms": 40}},
                {"timestamp": "2026-10-14T01:01:00Z",
                 "jsonPayload": {"cache": "miss", "reason": "capped", "latency_ms": 3}},
            ]  # fmt: skip
        if "explain" in query:
            return [
                {
                    "timestamp": "2026-10-14T01:00:00Z",
                    "jsonPayload": {"cache": "hit", "latency_ms": 40},
                }
            ]
        if "/annotations" in query:
            return [
                {
                    "timestamp": "2026-10-14T02:00:00Z",
                    "httpRequest": {
                        "latency": "0.120s",
                        "requestUrl": f"https://api.example/v1/content/{cid}/annotations",
                    },
                }
            ]
        return []  # fmt: skip

    out = eval_ops.report(eval_ops.collect(ReadOnlyClient(data), logs))
    assert "Total to date: $2.0000 over 2 days" in out and "75%" in out and "120 ms" in out
    assert "explanation request, generated" not in out  # the capped request is left out
    assert "library (corpus)" in out and "12 provider calls (2026-10-14 to 2026-10-14" in out
    assert not PRIVATE.search(out)


def test_the_script_never_loads_the_llm_module():
    code = "import sys, scripts.eval_ops; print('app.llm' in sys.modules)"
    run = subprocess.run([sys.executable, "-c", code], cwd=API, capture_output=True, text=True)
    assert run.stdout.strip() == "False", run.stderr[-400:]


@pytest.mark.skipif(
    not (API / "evals" / "ops_report.md").exists(), reason="report not generated yet"
)
def test_the_committed_report_publishes_no_ids():
    assert not PRIVATE.search((API / "evals" / "ops_report.md").read_text())


def test_an_empty_rolling_window_is_not_shown_as_zero():
    got = eval_ops.with_samples({"cached_p95_ms": 114.0, "cached_n": 40,
                                 "generated_p95_ms": 0.0, "generated_n": 0})  # fmt: skip
    assert got == {"cached_p95_ms": 114.0}
