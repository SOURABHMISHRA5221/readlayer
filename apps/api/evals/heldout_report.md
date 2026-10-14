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

### 2026-10-10T13:37:14+00:00 · seeded-local

Graph 2026-10-10-seeded (5201 concepts, sha 0cc0554780aec275), link_confirm-v3, threshold 0.865, new spend $0.1723, model fallbacks 0.

| group | n | exact-name | model-confirmed | unlinked | **linked** |
|---|---|---|---|---|---|
| business (total) | 186 | 111 (60%) | 8 (4%) | 67 (36%) | **64%** |
| non-business (total) | 156 | 17 (11%) | 4 (3%) | 135 (87%) | **13%** |
| new 15 (untuned) | 156 | 17 (11%) | 4 (3%) | 135 (87%) | **13%** |
| all 30 | 342 | 128 (37%) | 12 (4%) | 202 (59%) | **41%** |
|   business | 37 | 15 (41%) | 2 (5%) | 20 (54%) | **46%** |
|   culture | 6 | 0 (0%) | 0 (0%) | 6 (100%) | **0%** |
|   education | 14 | 5 (36%) | 1 (7%) | 8 (57%) | **43%** |
|   environment | 22 | 1 (5%) | 3 (14%) | 18 (82%) | **18%** |
|   finance | 103 | 72 (70%) | 3 (3%) | 28 (27%) | **73%** |
|   health | 22 | 3 (14%) | 0 (0%) | 19 (86%) | **14%** |
|   law | 16 | 2 (12%) | 0 (0%) | 14 (88%) | **12%** |
|   policy | 46 | 24 (52%) | 3 (7%) | 19 (41%) | **59%** |
|   politics | 28 | 3 (11%) | 0 (0%) | 25 (89%) | **11%** |
|   science | 31 | 2 (6%) | 0 (0%) | 29 (94%) | **6%** |
|   sports | 5 | 1 (20%) | 0 (0%) | 4 (80%) | **20%** |
|   technology | 12 | 0 (0%) | 0 (0%) | 12 (100%) | **0%** |

Stop check: business under 75%; non-business total under 50%; culture under 50% (n=6); education under 50% (n=14); environment under 50% (n=22); health under 50% (n=22); law under 50% (n=16); politics under 50% (n=28); science under 50% (n=31); sports under 50% (n=5); technology under 50% (n=12)

**Number 2, after growth (production behaviour: includes concepts grown from the article itself; never the headline):**

| group | n | exact-name | model-confirmed | grown here | unlinked | **linked** |
|---|---|---|---|---|---|---|
| business (total) | 186 | 111 (60%) | 9 (5%) | 46 (25%) | 20 (11%) | **89%** |
| non-business (total) | 156 | 17 (11%) | 6 (4%) | 84 (54%) | 49 (31%) | **69%** |
| new 15 (untuned) | 156 | 17 (11%) | 6 (4%) | 84 (54%) | 49 (31%) | **69%** |
| all 30 | 342 | 128 (37%) | 15 (4%) | 130 (38%) | 69 (20%) | **80%** |
|   business | 37 | 15 (41%) | 2 (5%) | 17 (46%) | 3 (8%) | **92%** |
|   culture | 6 | 0 (0%) | 0 (0%) | 5 (83%) | 1 (17%) | **83%** |
|   education | 14 | 5 (36%) | 1 (7%) | 5 (36%) | 3 (21%) | **79%** |
|   environment | 22 | 1 (5%) | 3 (14%) | 13 (59%) | 5 (23%) | **77%** |
|   finance | 103 | 72 (70%) | 4 (4%) | 18 (17%) | 9 (9%) | **91%** |
|   health | 22 | 3 (14%) | 2 (9%) | 11 (50%) | 6 (27%) | **73%** |
|   law | 16 | 2 (12%) | 0 (0%) | 8 (50%) | 6 (38%) | **62%** |
|   policy | 46 | 24 (52%) | 3 (7%) | 11 (24%) | 8 (17%) | **83%** |
|   politics | 28 | 3 (11%) | 0 (0%) | 13 (46%) | 12 (43%) | **57%** |
|   science | 31 | 2 (6%) | 0 (0%) | 15 (48%) | 14 (45%) | **55%** |
|   sports | 5 | 1 (20%) | 0 (0%) | 4 (80%) | 0 (0%) | **100%** |
|   technology | 12 | 0 (0%) | 0 (0%) | 10 (83%) | 2 (17%) | **83%** |

Concepts grown in memory: 94; a seeded sample of 30 is saved with the run for Number 3 (verdicts below).

**Number 3, grown-concept precision (judged by me against the four criteria in plan §E.5; seeded sample of 30 of 94): 26/30 = 87% (target ≥ 90%).**

| # | concept | verdict | reason |
|---|---|---|---|
| 1 | Point break | pass | real surfing term, correct definition, sports, matches 'point breaks' |
| 2 | Emergency declaration | pass | real policy instrument; definition general (the sentence is US federal) |
| 3 | Zionism | pass | real concept, neutral definition, politics |
| 4 | Expression of interest | pass | matches 'EOIs', business |
| 5 | Residential social care | pass | real concept, society, matches |
| 6 | Pre-apprenticeship route | pass (borderline) | a proposed pathway, defined generically; GB |
| 7 | Asbestos cement | pass | real material; environment acceptable |
| 8 | Asbestos | pass | real, correct |
| 9 | Trade diversification | pass | real, economics, matches |
| 10 | Prostate-specific antigen | pass | matches 'PSA levels', health |
| 11 | Underground wildfire hot spots | FAIL | invented label; the established term is 'hot spot' (criterion 1) |
| 12 | Post-tropical cyclone | pass | real, correct |
| 13 | Nuclear fuel cycle | FAIL | '18-month fuel cycle' is a reactor's refuelling interval, not the mining-to-waste cycle (criterion 4) |
| 14 | Disability benefit | pass | real, policy |
| 15 | Beach break | pass | real surfing term |
| 16 | Trading turnover | pass | real, distinct from trading volume (value vs quantity) |
| 17 | Quashed conviction | pass | real, law, matches 'quashed' |
| 18 | Standing instruction | pass | real banking term, matches |
| 19 | Saffir-Simpson scale | pass | explains 'category one hurricane' |
| 20 | Relief rally | pass | real market term |
| 21 | Treasury spokesman | pass | real role (party spokesperson); jurisdiction left global |
| 22 | Pre-vocational pathway | pass | real concept, education |
| 23 | Core catcher | FAIL | real nuclear safety device but filed under environment, not technology/science (criterion 3) |
| 24 | Copper concentrate | pass | real commodity term |
| 25 | Asbestosis | pass | real condition, health |
| 26 | Matcha | pass (borderline) | a product type a reader may not know; culture acceptable |
| 27 | Limiting global warming to 1.5C | pass | explains 'keep 1.5C alive' |
| 28 | Hyperfixation | pass | real concept, matches |
| 29 | Budget reallocation | FAIL | generic word ('reallocating') dressed as a concept (criterion 1) |
| 30 | Dangerous offender | pass | explains 'dangerousness', law |

### 2026-10-10T13:46:57+00:00 · seeded-growth-v2

Graph 2026-10-10-seeded (5201 concepts, sha 0cc0554780aec275), link_confirm-v3, threshold 0.865, new spend $0.1523, model fallbacks 0.

| group | n | exact-name | model-confirmed | unlinked | **linked** |
|---|---|---|---|---|---|
| business (total) | 186 | 111 (60%) | 8 (4%) | 67 (36%) | **64%** |
| non-business (total) | 156 | 17 (11%) | 4 (3%) | 135 (87%) | **13%** |
| new 15 (untuned) | 156 | 17 (11%) | 4 (3%) | 135 (87%) | **13%** |
| all 30 | 342 | 128 (37%) | 12 (4%) | 202 (59%) | **41%** |
|   business | 37 | 15 (41%) | 2 (5%) | 20 (54%) | **46%** |
|   culture | 6 | 0 (0%) | 0 (0%) | 6 (100%) | **0%** |
|   education | 14 | 5 (36%) | 1 (7%) | 8 (57%) | **43%** |
|   environment | 22 | 1 (5%) | 3 (14%) | 18 (82%) | **18%** |
|   finance | 103 | 72 (70%) | 3 (3%) | 28 (27%) | **73%** |
|   health | 22 | 3 (14%) | 0 (0%) | 19 (86%) | **14%** |
|   law | 16 | 2 (12%) | 0 (0%) | 14 (88%) | **12%** |
|   policy | 46 | 24 (52%) | 3 (7%) | 19 (41%) | **59%** |
|   politics | 28 | 3 (11%) | 0 (0%) | 25 (89%) | **11%** |
|   science | 31 | 2 (6%) | 0 (0%) | 29 (94%) | **6%** |
|   sports | 5 | 1 (20%) | 0 (0%) | 4 (80%) | **20%** |
|   technology | 12 | 0 (0%) | 0 (0%) | 12 (100%) | **0%** |

Stop check: business under 75%; non-business total under 50%; culture under 50% (n=6); education under 50% (n=14); environment under 50% (n=22); health under 50% (n=22); law under 50% (n=16); politics under 50% (n=28); science under 50% (n=31); sports under 50% (n=5); technology under 50% (n=12)

**Number 2, after growth (production behaviour: includes concepts grown from the article itself; never the headline):**

| group | n | exact-name | model-confirmed | grown here | unlinked | **linked** |
|---|---|---|---|---|---|---|
| business (total) | 186 | 111 (60%) | 9 (5%) | 45 (24%) | 21 (11%) | **89%** |
| non-business (total) | 156 | 17 (11%) | 6 (4%) | 80 (51%) | 53 (34%) | **66%** |
| new 15 (untuned) | 156 | 17 (11%) | 6 (4%) | 80 (51%) | 53 (34%) | **66%** |
| all 30 | 342 | 128 (37%) | 15 (4%) | 125 (37%) | 74 (22%) | **78%** |
|   business | 37 | 15 (41%) | 2 (5%) | 18 (49%) | 2 (5%) | **95%** |
|   culture | 6 | 0 (0%) | 0 (0%) | 5 (83%) | 1 (17%) | **83%** |
|   education | 14 | 5 (36%) | 1 (7%) | 4 (29%) | 4 (29%) | **71%** |
|   environment | 22 | 1 (5%) | 3 (14%) | 12 (55%) | 6 (27%) | **73%** |
|   finance | 103 | 72 (70%) | 4 (4%) | 16 (16%) | 11 (11%) | **89%** |
|   health | 22 | 3 (14%) | 2 (9%) | 11 (50%) | 6 (27%) | **73%** |
|   law | 16 | 2 (12%) | 0 (0%) | 6 (38%) | 8 (50%) | **50%** |
|   policy | 46 | 24 (52%) | 3 (7%) | 11 (24%) | 8 (17%) | **83%** |
|   politics | 28 | 3 (11%) | 0 (0%) | 13 (46%) | 12 (43%) | **57%** |
|   science | 31 | 2 (6%) | 0 (0%) | 15 (48%) | 14 (45%) | **55%** |
|   sports | 5 | 1 (20%) | 0 (0%) | 4 (80%) | 0 (0%) | **100%** |
|   technology | 12 | 0 (0%) | 0 (0%) | 10 (83%) | 2 (17%) | **83%** |

Concepts grown in memory: 90; a seeded sample of 30 is saved with the run for Number 3 (verdicts below).

**Number 3 after tightening (growth confirms each concept with link_confirm; concept_define v4 scopes): 29/30 = 97% (target ≥ 90%).** Not independent of the first sample: both fixes were prompted by its failures, and about two-thirds of this sample overlaps it (same articles, same seed). Gone vs the first sample: 'Nuclear fuel cycle' and 'Budget reallocation' (rejected by the confirm step); 'Core catcher' now technology. Still failing: an invented label.

| # | concept | verdict | note |
|---|---|---|---|
| 1 | 1.5C global warming target | pass |  |
| 2 | Emergency declaration | pass | definition is the US federal sense; jurisdiction left global |
| 3 | Apartheid (crime) | pass |  |
| 4 | Expression of interest | pass |  |
| 5 | Residential social care | pass |  |
| 6 | Apprenticeship readiness scheme | pass (borderline) | a proposed scheme, defined generically |
| 7 | Asbestos cement | pass |  |
| 8 | Asbestos | pass |  |
| 9 | Copper concentrate | pass |  |
| 10 | Prostate-specific antigen | pass |  |
| 11 | Underground wildfire hot spots | FAIL | invented label (criterion 1); the confirm step accepts the definition |
| 12 | Post-tropical cyclone | pass |  |
| 13 | Core catcher | pass | now technology (concept_define v4 scopes) |
| 14 | Pre-apprenticeship route | pass (borderline) |  |
| 15 | Beach break | pass |  |
| 16 | Trading turnover | pass |  |
| 17 | Treasury spokesman | pass |  |
| 18 | Standing instruction | pass |  |
| 19 | Saffir-Simpson scale | pass |  |
| 20 | Relief rally | pass |  |
| 21 | Frontbench | pass |  |
| 22 | Pre-vocational pathway | pass |  |
| 23 | Electronic Gold Receipt | pass |  |
| 24 | Preferential trade agreement | pass | distinct from Preferential tariffs and Free trade agreement |
| 25 | Asbestosis | pass |  |
| 26 | Matcha | pass (borderline) |  |
| 27 | Point break | pass |  |
| 28 | Post-traumatic stress disorder | pass |  |
| 29 | Digital identity | pass |  |
| 30 | Women's suffrage | pass | explains 'female suffrage' |

### 2026-10-10T13:50:24+00:00 · seeded-final

Graph 2026-10-10-seeded (5201 concepts, sha 0cc0554780aec275), link_confirm-v3, threshold 0.865, new spend $0.0000, model fallbacks 0.

| group | n | exact-name | model-confirmed | unlinked | **linked** |
|---|---|---|---|---|---|
| business (total) | 186 | 111 (60%) | 8 (4%) | 67 (36%) | **64%** |
| non-business (total) | 156 | 17 (11%) | 4 (3%) | 135 (87%) | **13%** |
| new 15 (untuned) | 156 | 17 (11%) | 4 (3%) | 135 (87%) | **13%** |
| all 30 | 342 | 128 (37%) | 12 (4%) | 202 (59%) | **41%** |
|   business | 37 | 15 (41%) | 2 (5%) | 20 (54%) | **46%** |
|   culture | 6 | 0 (0%) | 0 (0%) | 6 (100%) | **0%** |
|   education | 14 | 5 (36%) | 1 (7%) | 8 (57%) | **43%** |
|   environment | 22 | 1 (5%) | 3 (14%) | 18 (82%) | **18%** |
|   finance | 103 | 72 (70%) | 3 (3%) | 28 (27%) | **73%** |
|   health | 22 | 3 (14%) | 0 (0%) | 19 (86%) | **14%** |
|   law | 16 | 2 (12%) | 0 (0%) | 14 (88%) | **12%** |
|   policy | 46 | 24 (52%) | 3 (7%) | 19 (41%) | **59%** |
|   politics | 28 | 3 (11%) | 0 (0%) | 25 (89%) | **11%** |
|   science | 31 | 2 (6%) | 0 (0%) | 29 (94%) | **6%** |
|   sports | 5 | 1 (20%) | 0 (0%) | 4 (80%) | **20%** |
|   technology | 12 | 0 (0%) | 0 (0%) | 12 (100%) | **0%** |

Stop check: business under 75%; non-business total under 50%; culture under 50% (n=6); education under 50% (n=14); environment under 50% (n=22); health under 50% (n=22); law under 50% (n=16); politics under 50% (n=28); science under 50% (n=31); sports under 50% (n=5); technology under 50% (n=12)

**Number 2, after growth (production behaviour: includes concepts grown from the article itself; never the headline):**

| group | n | exact-name | model-confirmed | grown here | unlinked | **linked** |
|---|---|---|---|---|---|---|
| business (total) | 186 | 111 (60%) | 9 (5%) | 45 (24%) | 21 (11%) | **89%** |
| non-business (total) | 156 | 17 (11%) | 6 (4%) | 80 (51%) | 53 (34%) | **66%** |
| new 15 (untuned) | 156 | 17 (11%) | 6 (4%) | 80 (51%) | 53 (34%) | **66%** |
| all 30 | 342 | 128 (37%) | 15 (4%) | 125 (37%) | 74 (22%) | **78%** |
|   business | 37 | 15 (41%) | 2 (5%) | 18 (49%) | 2 (5%) | **95%** |
|   culture | 6 | 0 (0%) | 0 (0%) | 5 (83%) | 1 (17%) | **83%** |
|   education | 14 | 5 (36%) | 1 (7%) | 4 (29%) | 4 (29%) | **71%** |
|   environment | 22 | 1 (5%) | 3 (14%) | 12 (55%) | 6 (27%) | **73%** |
|   finance | 103 | 72 (70%) | 4 (4%) | 16 (16%) | 11 (11%) | **89%** |
|   health | 22 | 3 (14%) | 2 (9%) | 11 (50%) | 6 (27%) | **73%** |
|   law | 16 | 2 (12%) | 0 (0%) | 6 (38%) | 8 (50%) | **50%** |
|   policy | 46 | 24 (52%) | 3 (7%) | 11 (24%) | 8 (17%) | **83%** |
|   politics | 28 | 3 (11%) | 0 (0%) | 13 (46%) | 12 (43%) | **57%** |
|   science | 31 | 2 (6%) | 0 (0%) | 15 (48%) | 14 (45%) | **55%** |
|   sports | 5 | 1 (20%) | 0 (0%) | 4 (80%) | 0 (0%) | **100%** |
|   technology | 12 | 0 (0%) | 0 (0%) | 10 (83%) | 2 (17%) | **83%** |

Concepts grown in memory: 90; a seeded sample of 30 is saved with the run for Number 3 (verdicts below).

**Spot-check of 10 model-confirmed links (seeded-final run, seed 34): 3 wrong (target ≤ 2) — missed.**
Correct: "transition away from fossil fuels" → Energy transition (×2), "equity mutual funds" → Mutual funds,
"regional mayors" → Metro mayors, "amalgamation" → Merger, "SMEs" → MSME, "national care service" → National
social care service. Wrong: "tax and spend" → Fiscal policy (a broader field), "net profit" → Consolidated net
profit (a narrower concept), "molybdenum" → Element (a generic category; a seeded chemistry concept).

## Number 3, fresh sample from production growth (M9 part 2, 2026-10-14)

**27/30 = 90% (target ≥ 90%).** Population: the 78 concepts grown live in production from
22 readers' and library pages, Oct 10–14 (`added_at` ≤ 2026-10-14 09:24:55 UTC), all after the
decision 36 tightening; none was in the two M2.2 samples. A seeded random 30
(`evals/grown_sample.json`: population ids, seed 1015, committed before judging). Same four
criteria as M2.2 §E.5: (1) a real, established term; (2) a correct definition; (3) the right
domain; (4) it matches the mention, and a duplicate of another grown concept fails.

**Disclosure.** The verdicts are by the implementing agent, the same one that wrote the M9 part 2
fixes; it saw all 78 concepts while gathering that evidence, so the sample is independent of tuning
but not of the judge. Sourabh is asked to audit these 30. The source sentences are kept out of this
public repo (some come from readers' own pages); only the fields below are published.

All three samples: 87% (M2.2 first, 26/30), 97% (after tightening, 29/30, overlapping the first),
**90% (fresh, 27/30)**.

| # | concept | domain | kind | source | verdict | reason |
|---|---|---|---|---|---|---|
| 1 | Blasphemy | law | idea | extension | pass | real term, correct definition, right domain, matches the mention |
| 2 | Lethal injection | law | method | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 3 | Silicon-carbon battery | technology | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 4 | Tax-aware investing | finance | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 5 | Phishing | technology | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 6 | Humanoid robot | technology | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 7 | Programmable Power Supply | technology | jargon | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 8 | Linear algebra | science | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 9 | Seizure memo | law | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 10 | Adjournment motion | politics | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 11 | BSS section | technology | jargon | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 12 | Pregabalin | health | condition | extension | pass | pass; kind 'condition' is wrong (a drug), kind is not one of the four criteria |
| 13 | Special Intensive Revision | politics | policy | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 14 | System of linear equations | science | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 15 | Node (graph theory) | technology | idea | extension | pass | real term, correct definition, right domain, matches the mention |
| 16 | Natural language processing | technology | idea | extension | pass | real term, correct definition, right domain, matches the mention |
| 17 | No-cost EMI | finance | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 18 | PFAS | environment | idea | fetch | FAIL | fails criterion 4: a duplicate of 'Forever chemicals' grown from the same page (R9: duplicates fail) |
| 19 | Watch and Ward | politics | entity_type | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 20 | Peer-to-peer transaction | finance | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 21 | Rule of law | law | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 22 | Circle Inspector and Sub-Inspector | law | role | user_ingested | FAIL | fails criterion 1: two police ranks fused into one invented label |
| 23 | Alarm photosynthesis | science | idea | user_ingested | FAIL | fails criterion 2: definition too vague (it never says CO2 comes from calcium oxalate crystals) |
| 24 | Qualcomm Snapdragon 8 Elite | technology | jargon | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 25 | Tax-loss harvesting | finance | method | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 26 | Education Minister | politics | role | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 27 | Knowledge graph | technology | idea | extension | pass | real term, correct definition, right domain, matches the mention |
| 28 | Assembler | technology | method | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 29 | Antisemitism | society | idea | user_ingested | pass | real term, correct definition, right domain, matches the mention |
| 30 | Calendar phishing | technology | jargon | user_ingested | pass | real term, correct definition, right domain, matches the mention |
