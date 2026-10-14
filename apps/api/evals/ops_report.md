# Cost, cache and latency (M9 part 3)

Generated 2026-10-14 10:46 UTC by `scripts/eval_ops.py` from production, read only: Firestore (field masks) and Cloud Logging for the last 7 days (2026-10-08 to 2026-10-14). Aggregates only. Minimum instances is 0, so latencies include cold starts.

## Cost per article (model calls stored with each page)

Analysis: demand extraction and linking (growth's confirm step shares the linker's `link_confirm` task, so it counts here). Growth: concept_define, link_merge, concept_prereqs. Transcript: a recording's transcription, once.

| pages | n | analysis median / mean / p90 | growth median / mean | transcript mean |
|---|---|---|---|---|
| extension | 9 | $0.0035 / $0.0050 / $0.0118 | $0.0000 / $0.0011 | — |
| fetch | 323 | $0.0045 / $0.0084 / $0.0239 | $0.0000 / $0.0000 | — |
| media | 4 | $0.0075 / $0.0086 / $0.0128 | $0.0031 / $0.0031 | $0.0333 |
| user_ingested | 25 | $0.0047 / $0.0080 / $0.0142 | $0.0014 / $0.0014 | — |

## Cost per explanation part (current prompt versions)

| part | n | median | mean |
|---|---|---|---|
| background | 80 | $0.0038 | $0.0041 |
| restatement | 66 | $0.0038 | $0.0040 |
| restatement (definition-only) | 2 | $0.0034 | $0.0034 |

The restatement is made once per span and shared by every reader; the Background once per span, band, analogy domain and style. A card's cost to a reader is therefore usually a cache hit, not the sum of the two.

## Cache

| cache | hits | generated / ingested | hit rate | source |
|---|---|---|---|---|
| explanations | 468 | 203 | 70% | `ops/explain/days`, last 6 days |
| pages opened (Open here, Read any link) | 3 | 25 | 11% | `rec opened` log lines: already stored vs fetched new |

Web search: 412 provider calls over the window (cache misses; no hit counter exists).

## Latency

| what | n | p50 | p95 | source |
|---|---|---|---|---|
| annotations route (request) | 314 | 73 ms | 287 ms | Cloud Run request logs, `/annotations`, 200 |
| explain, cached | 290 | 47 ms | 127 ms | `explain` log line `latency_ms` |
| explain, generated | 156 | 9862 ms | 30330 ms | `explain` log line `latency_ms` |

## Model spend on the project ledger

All model spend recorded in `ops/spend/days` (readers, plus local evals, seeding and warm runs on production credentials). **Total to date: $22.6418 over 8 days.**

| day (UTC) | spend |
|---|---|
| 2026-10-04 | $10.6671 |
| 2026-10-05 | $0.0170 |
| 2026-10-09 | $2.9004 |
| 2026-10-10 | $7.0658 |
| 2026-10-11 | $0.5689 |
| 2026-10-12 | $0.3212 |
| 2026-10-13 | $0.6543 |
| 2026-10-14 | $0.4472 |
