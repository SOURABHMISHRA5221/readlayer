# Cross-domain prerequisite replay (M9 part 2, R7–R8)

78 concepts grown live up to 2026-10-14T09:24:55.300000+00:00; pools as growth builds them now, minus the concept; one batched `concept_prereqs` on MODEL_FAST, $0.0198. 83 edges, 32 cross-domain.
Every cross-domain edge was judged right or wrong with the confidences hidden (borderline counts as wrong) and the verdicts committed (`prereq_verdicts.json`) before this join.

**CROSS_DOMAIN_MIN = 0.7**: of 22 right cross-domain edges 0 dropped; of 10 wrong, 0 dropped and 10 kept. Chosen and measured on the same set (in-sample).

*The next three paragraphs and the cut table were added by hand after `report` ran (re-running it would drop them).*

**No cut separates them.** The model gives coarse confidences (0.7–0.9) and wrong edges sit as high as right ones (Seizure memo → Seizure at 0.90). Every possible cut:

| keep confidence ≥ | right kept | wrong dropped |
|---|---|---|
| 0.70 | 22/22 (100%) | 0/10 |
| 0.80 | 16/22 (72%) | 2/10 |
| 0.85 | 7/22 (31%) | 9/10 |
| 0.90 | 6/22 (27%) | 9/10 |

So `CROSS_DOMAIN_MIN` is **not added** (the only cut keeping ≥ 90% of right edges is the lowest, which drops nothing). A same-domain rule would drop 22 right edges of 32 here. Neither method the M2.2 follow-up named works on this evidence; the known wrong edges that are stored are filtered write-free (`KNOWN_WRONG_PREREQS`), and better prerequisites would need a prompt change with its own eval (after the freeze).

| concept | prerequisite | confidence | verdict | kept |
|---|---|---|---|---|
| Battery penetration test | Lithium-ion battery | 0.90 | right | yes |
| Franchise T20 leagues | Twenty20 | 0.90 | right | yes |
| Lethal injection | Injection | 0.90 | right | yes |
| Qualcomm Snapdragon 8 Elite | Semiconductors | 0.90 | right | yes |
| Seizure memo | Seizure | 0.90 | wrong | yes |
| Twenty20 centuries | Twenty20 | 0.90 | right | yes |
| Zionism | Diaspora | 0.90 | right | yes |
| Pregabalin | Active pharmaceutical ingredient | 0.85 | right | yes |
| Apple A18 | Semiconductors | 0.80 | right | yes |
| C2 photorespiratory carbon pump | Carbon cycle | 0.80 | wrong | yes |
| Chief Election Commissioner | Elected office | 0.80 | wrong | yes |
| Contempt of court | Supreme court | 0.80 | right | yes |
| Education Minister | Elected office | 0.80 | right | yes |
| Executive Magistrate | Administration | 0.80 | wrong | yes |
| Forever chemicals | Chemistry | 0.80 | right | yes |
| Franchise T20 leagues | Franchise | 0.80 | wrong | yes |
| Permanent Account Number | Financial account | 0.80 | wrong | yes |
| Phase 1 environmental site assessment | Environmental science | 0.80 | right | yes |
| Programmable Power Supply | Electric current | 0.80 | right | yes |
| Proper officer | Administration | 0.80 | wrong | yes |
| Silicon-carbon battery | Lithium-ion battery | 0.80 | right | yes |
| Tax-loss harvesting | Tax liability | 0.80 | right | yes |
| Wearable technology | Human body | 0.80 | wrong | yes |
| White-ball cricket | Twenty20 | 0.80 | right | yes |
| Blasphemy | Belief | 0.70 | right | yes |
| Circle Inspector and Sub-Inspector | Administration | 0.70 | wrong | yes |
| Education Minister | Administration | 0.70 | wrong | yes |
| Honeymoon period (politics) | Electoral cycle | 0.70 | right | yes |
| Humanoid robot | AI | 0.70 | right | yes |
| Natural language processing | AI | 0.70 | right | yes |
| Phase 2 environmental site assessment | Environmental science | 0.70 | right | yes |
| USB Power Delivery | Electric power | 0.70 | right | yes |

*Added by hand.* **Which wrong edges are stored** (production `graph_growth`, read 2026-10-14 before the
replay): stored — Seizure memo → Seizure, C2 photorespiratory carbon pump → Carbon cycle, Franchise T20
leagues → Franchise, Wearable technology → Human body, Education Minister → Administration; not stored
(the replay proposed them, production has other prerequisites) — Executive Magistrate → Administration
(stored: Jurisdiction), Proper officer → Administration (none), Circle Inspector and Sub-Inspector →
Administration (none), Chief Election Commissioner → Elected office (none), Permanent Account Number →
Financial account (stored: KYC). All ten are in `app/graph/prereq_fixes.py`, with the four from the
plan's evidence (13 pairs, one overlapping). **Measured rate for new growth:** 10 of 32 cross-domain
proposals wrong (31%), at confidences up to 0.90; same-domain proposals were not judged.
