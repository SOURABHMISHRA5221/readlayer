# Held-out linker evaluation (M2.2, decision 34)

30 held-out articles, never used to build the graph: lines 1–15 are the M2.1 business set,
lines 16–30 the M2.2 non-business set (domains fixed in data/heldout_urls.txt before any run).
Number 1, the headline, is the **frozen-graph** link rate: every concept/term demand re-linked in
memory against a fixed graph file, no growth. Targets: business ≥ 75%, non-business aim 60%,
under 50% (total or any domain) stops the milestone for Sourabh. The **new 15** row is untouched
by any tuning; the old 15 informed the M2.2 fixes (Chancellor, levy, Russell examples).
LINK_THRESHOLD 0.865 for every run.

## Run log (every run, in order)

### 2026-10-10T12:39:29+00:00 · before

Graph 2026-10-04 (3327 concepts, sha 58447b11ca3a2534), link_confirm-v2, threshold 0.865, new spend $0.1554, model fallbacks 0.

| group | n | exact-name | model-confirmed | unlinked | **linked** |
|---|---|---|---|---|---|
| business (total) | 186 | 106 (57%) | 7 (4%) | 73 (39%) | **61%** |
| non-business (total) | 156 | 13 (8%) | 4 (3%) | 139 (89%) | **11%** |
| new 15 (untuned) | 156 | 13 (8%) | 4 (3%) | 139 (89%) | **11%** |
| all 30 | 342 | 119 (35%) | 11 (3%) | 212 (62%) | **38%** |
|   business | 37 | 15 (41%) | 2 (5%) | 20 (54%) | **46%** |
|   culture | 6 | 0 (0%) | 0 (0%) | 6 (100%) | **0%** |
|   education | 14 | 5 (36%) | 1 (7%) | 8 (57%) | **43%** |
|   environment | 22 | 0 (0%) | 3 (14%) | 19 (86%) | **14%** |
|   finance | 103 | 69 (67%) | 3 (3%) | 31 (30%) | **70%** |
|   health | 22 | 2 (9%) | 0 (0%) | 20 (91%) | **9%** |
|   law | 16 | 1 (6%) | 0 (0%) | 15 (94%) | **6%** |
|   policy | 46 | 22 (48%) | 2 (4%) | 22 (48%) | **52%** |
|   politics | 28 | 3 (11%) | 0 (0%) | 25 (89%) | **11%** |
|   science | 31 | 2 (6%) | 0 (0%) | 29 (94%) | **6%** |
|   sports | 5 | 0 (0%) | 0 (0%) | 5 (100%) | **0%** |
|   technology | 12 | 0 (0%) | 0 (0%) | 12 (100%) | **0%** |

Stop check: business under 75%; non-business total under 50%; culture under 50% (n=6); education under 50% (n=14); environment under 50% (n=22); health under 50% (n=22); law under 50% (n=16); politics under 50% (n=28); science under 50% (n=31); sports under 50% (n=5); technology under 50% (n=12)
