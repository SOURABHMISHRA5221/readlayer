# Glossary seeding dry run (M2.2, decision 34)

2026-10-10T13:16:24+00:00 · from graph 2026-10-04 (3327 concepts) → 5629 concepts (2302 new, overrides included). Nothing uploaded or written to Firestore.

## Pipeline per glossary group (domain hint)

| hint | pages | parsed | exact match (dropped) | duplicate | ranked out | to dedupe | merged into graph | merged together | defined | dropped by kind | new |
|---|---|---|---|---|---|---|---|---|---|---|---|
| culture | 5 | 2312 | 7 | 81 | 1924 | 300 | 7 | 27 | 268 | generic 2, company 2 | 264 |
| economics | 1 | 1049 | 284 | 28 | 437 | 300 | 21 | 19 | 261 | generic 1 | 260 |
| education | 7 | 80 | 1 | 4 | 0 | 75 | 0 | 5 | 65 | event 1 | 64 |
| environment | 3 | 1072 | 26 | 164 | 582 | 300 | 7 | 26 | 263 | place 3, generic 2 | 258 |
| health | 3 | 1448 | 5 | 126 | 1017 | 300 | 2 | 23 | 271 | event 1 | 270 |
| law | 3 | 219 | 2 | 1 | 0 | 216 | 3 | 16 | 186 | event 1 | 185 |
| politics | 3 | 218 | 8 | 4 | 0 | 206 | 6 | 9 | 189 | event 10, place 3 | 176 |
| science | 5 | 2699 | 30 | 208 | 2161 | 300 | 2 | 19 | 282 | event 1 | 281 |
| sports | 5 | 1799 | 18 | 104 | 1377 | 300 | 4 | 33 | 279 | generic 4, place 2, event 1 | 272 |
| technology | 4 | 1590 | 21 | 55 | 1214 | 300 | 7 | 26 | 271 | company 1 | 270 |

## Concepts per taxonomy domain (final, as concept_define assigned them)

| domain | total | new |
|---|---|---|
| economics | 1263 | 199 |
| finance | 1320 | 41 |
| business | 467 | 40 |
| policy | 592 | 35 |
| politics | 122 | 122 |
| law | 218 | 218 |
| technology | 235 | 235 |
| science | 395 | 395 |
| health | 217 | 217 |
| environment | 170 | 170 |
| sports | 271 | 271 |
| culture | 281 | 281 |
| education | 48 | 48 |
| society | 30 | 30 |

- Kind and jurisdiction for pre-M2.2 concepts: {'concept_jurisdiction': 3327}.
- Jurisdictions: {'global': 4882, 'US': 324, 'IN': 177, 'EU': 102, 'GB': 88, 'JP': 12, 'CN': 11, 'DE': 10}.
- Prerequisite edges on new concepts: 2990; cycle edges removed: 34.
- concepts.seeded.json 12.8 MB; parse + graph build 0.10 s locally.
- New LLM and embedding spend for this run: $1.721.

## 20 random new concepts (definition, domain, kind, prerequisites)

- **Long poem** (culture, idea, global): A lengthy poetic work that extends beyond the typical scope of short lyric poetry, often dealing with epic or philosophical themes. Prerequisites: Verse, Literature.
- **Data structure** (technology, idea, global): A specialized format for organizing, processing, and storing data efficiently within a computer system. Prerequisites: Computer science, Data type.
- **Computer network** (technology, idea, global): A collection of interconnected computing devices that can exchange data and share resources using digital links. Prerequisites: Computer, Network.
- **Validity opinion** (law, idea, global): A formal legal assessment provided by an attorney regarding whether an issued patent would likely be held valid if challenged in court. Prerequisites: Patentability opinion, Invalidity opinion.
- **Room** (technology, idea, global): An enclosed space or compartment within a virtual environment that forms part of a larger map. Prerequisites: Area.
- **Submarine patent** (law, idea, global): A patent that stays in the application stage for an unusually long time before finally being granted, surprising competitors. Prerequisites: Application, Prior art.
- **Cell plate** (science, idea, global): A structure that forms during cytokinesis in plant cells, helping to construct a new cell wall between the two newly formed daughter cells. It develops in the center of the cell and expands outward to fuse with the outer membrane. Prerequisites: Cell division, Cell.
- **Foundation species** (science, organism_type, global): A dominant primary producer species that plays a critical role in structuring an ecosystem through its high abundance and significant influence on other organisms. Prerequisites: Producer.
- **Transformation problem** (economics, idea, global): A theoretical challenge in Marxist economics concerning how to translate labor values into competitive market prices of commodities. It addresses the apparent contradiction between the labor theory of value and observed market profitability. Prerequisites: Labor theory of value, Marxian economics.
- **Vein** (health, idea, global): A blood vessel that carries deoxygenated blood back toward the heart from various body tissues. Prerequisites: Blood vessel, Heart.
- **European Administrative School** (politics, institution, EU): An interinstitutional body established to provide common training for staff members of European Union institutions. Prerequisites: European Commission.
- **Ben** (culture, jargon, global): A musical instruction directing a performer to play a passage well or distinctly. Prerequisites: none.
- **One-and-done** (sports, idea, US): A college basketball player who enters the professional draft after completing only a single university season. Prerequisites: none.
- **Climate movement** (society, idea, global): A decentralized social movement comprising activists, organizations, and citizens advocating for urgent policy action to mitigate climate change. Prerequisites: Climate change.
- **Score attack** (technology, idea, global): A video game mode focused purely on achieving the highest possible points rather than progressing through a story. Prerequisites: High score, Time attack.
- **Off side** (sports, idea, global): The half of the cricket pitch that is facing away from the batter's legs as they take their stance. Prerequisites: none.
- **Induced demand** (economics, idea, global): A phenomenon where increasing the capacity of a resource, such as expanding a highway, leads to a proportional increase in demand for it. Prerequisites: Demand.
- **Charge number** (science, jargon, global): A dimensionless number representing the total electric charge of an entity divided by the elementary charge constant. Prerequisites: Charge.
- **Receptors** (health, idea, global): Specialized protein structures on or within cells that bind to specific chemical signals to trigger cellular responses. Prerequisites: Cell, Protein.
- **Co-operation** (science, idea, global): The process where individuals or groups work or act together for mutual benefit or common goals. Prerequisites: Social behavior.
