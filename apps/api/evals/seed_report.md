# Glossary seeding dry run (M2.2, decision 34)

2026-10-10T13:20:13+00:00 · from graph 2026-10-04 (3327 concepts) → 5201 concepts (1874 new, overrides included). Nothing uploaded or written to Firestore.

## Pipeline per glossary group (domain hint)

| hint | pages | parsed | exact match (dropped) | duplicate | ranked out | to dedupe | merged into graph | merged together | defined | everyday word | dropped by kind | new |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| culture | 5 | 2312 | 7 | 81 | 1924 | 300 | 7 | 27 | 268 | 52 | company 2 | 214 |
| economics | 1 | 1049 | 284 | 28 | 437 | 300 | 21 | 19 | 261 | 27 | 0 | 234 |
| education | 7 | 80 | 1 | 4 | 0 | 75 | 0 | 5 | 65 | 2 | event 1 | 62 |
| environment | 3 | 1072 | 26 | 164 | 582 | 300 | 7 | 26 | 263 | 26 | place 3, generic 1 | 233 |
| health | 3 | 1448 | 5 | 126 | 1017 | 300 | 2 | 23 | 271 | 24 | event 1 | 246 |
| law | 3 | 219 | 2 | 1 | 0 | 216 | 3 | 16 | 186 | 6 | event 1 | 179 |
| politics | 3 | 218 | 8 | 4 | 0 | 206 | 6 | 9 | 189 | 6 | event 10, place 3 | 170 |
| science | 5 | 2699 | 30 | 208 | 2161 | 300 | 2 | 19 | 282 | 81 | event 1 | 200 |
| sports | 5 | 1799 | 18 | 104 | 1377 | 300 | 4 | 33 | 279 | 115 | generic 2, place 1, event 1 | 160 |
| technology | 4 | 1590 | 21 | 55 | 1214 | 300 | 7 | 26 | 271 | 96 | company 1 | 174 |

## Concepts per taxonomy domain (final, as concept_define assigned them)

| domain | total | new |
|---|---|---|
| economics | 1247 | 183 |
| finance | 1312 | 33 |
| business | 463 | 36 |
| policy | 592 | 35 |
| politics | 116 | 116 |
| law | 211 | 211 |
| technology | 148 | 148 |
| science | 310 | 310 |
| health | 193 | 193 |
| environment | 151 | 151 |
| sports | 162 | 162 |
| culture | 223 | 223 |
| education | 45 | 45 |
| society | 28 | 28 |

- Kind and jurisdiction for pre-M2.2 concepts: {'concept_jurisdiction': 3327}.
- Jurisdictions: {'global': 4462, 'US': 316, 'IN': 177, 'EU': 102, 'GB': 88, 'JP': 12, 'CN': 11, 'DE': 10}.
- Prerequisite edges on new concepts: 2031; cycle edges removed: 33.
- concepts.seeded.json 11.9 MB; parse + graph build 0.19 s locally.
- New LLM and embedding spend for this run: $0.452.

## 20 random new concepts (definition, domain, kind, prerequisites)

- **Cell cycle** (science, method, global): The structured series of stages that a cell goes through to grow and divide into two new daughter cells. It involves copying genetic material and dividing cellular components. Prerequisites: Cell division, DNA.
- **Producer** (science, idea, global): A producer in ecology is an autotrophic organism, such as a plant or alga, that creates its own food from inorganic substances using light or chemical energy. Prerequisites: Organic.
- **Cell theory** (science, idea, global): The fundamental scientific theory that all living organisms are composed of cells. Prerequisites: Cell division.
- **5–2 defense** (sports, idea, US): A football defensive formation utilizing five linemen and two linebackers. Prerequisites: none.
- **Bolar exemption** (law, policy, global): A legal exemption that allows researchers to use a patented invention for regulatory approval and testing without infringing the patent. Prerequisites: Infringement.
- **Backward design** (education, method, global): A curriculum planning method that starts by defining desired learning outcomes before designing assessments and instructional lessons. Prerequisites: Aims and objectives, Bloom's Taxonomy.
- **Male reproductive system** (health, idea, global): The biological system made up of external and internal organs that facilitate male reproduction. Prerequisites: Reproductive system.
- **European Parliament** (politics, institution, EU): The European Parliament is the directly elected legislative body of the European Union that represents citizens and shares lawmaking powers. Prerequisites: none.
- **Salt bridge** (science, instrument, global): A laboratory device used to connect the oxidation and reduction half-cells of a galvanic cell while maintaining electrical neutrality. Prerequisites: Reduction.
- **Level editor** (technology, method, global): A software tool built into a game or provided separately that lets users design and create custom game levels. Prerequisites: Level design, Game engine.
- **Prosecution history estoppel** (law, idea, US): A legal rule preventing a patent owner from later arguing an interpretation of patent claims that they disavowed or narrowed during the initial application process. Prerequisites: Claim construction.
- **Location model** (economics, idea, global): An economic framework used to determine the optimal geographical placement of production facilities or services based on transport costs and market access. Prerequisites: Input costs, Economics.
- **Water productivity** (environment, idea, global): A measure of how efficiently water is used to produce goods, services, or agricultural yields. Prerequisites: Water resources.
- **Off theory** (sports, method, global): A controversial bowling tactic where multiple fielders are placed on the leg side to deter scoring. Prerequisites: none.
- **Birth rate** (society, jargon, global): The number of live births occurring in a population relative to its total size over a specified time period. Prerequisites: none.
- **Kind code** (law, jargon, global): A letter and digit code assigned to a patent document to indicate its specific publication stage, such as an application or a granted patent. Prerequisites: Pre-grant Publication.
- **Curriculum-based measurement** (education, method, global): A method of frequently evaluating students using brief, direct assessments tied directly to their everyday classroom curriculum. Prerequisites: none.
- **Low comedy** (culture, idea, global): A form of comedic performance that relies on physical slapstick, crude humor, and exaggerated situations rather than subtle wit. Prerequisites: Humor.
- **Street football** (sports, idea, global): Informal variations of football played in streets, courtyards, or other non-traditional spaces. Prerequisites: none.
- **Capital cost** (business, jargon, global): The total upfront financial expenditure required to acquire physical assets such as land, buildings, and machinery for a business. Prerequisites: Capital expenditures, Capital asset.
