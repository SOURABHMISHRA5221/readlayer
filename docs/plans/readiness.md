# Readiness score on For you (decision 60, 2026-10-14)

Sourabh: "Add readiness Score" (after a list of knowledge-map features; this is the one sized at
≤ 1 day before the Oct 16 freeze). Branch `readiness` from `main` at b41dbf7.

## What the reader sees
Each For you row gets one line under the title, from the reader's own map:
- **"Mostly familiar"**: the item names no idea new to this reader;
- **"Ready for you"**: 1–4 new ideas and the reader already has their groundwork;
- **"A stretch: read up on X and Y first"**: more than 4 new ideas, or a new idea with a
  prerequisite that is itself new to the reader (X, Y: up to two such prerequisites, the most
  basic first).
A goal line ("Picked for your goal …") stays and comes first; readiness follows on the same
line. The "N ideas new to you" count in the meta line is unchanged.

## API (pure, `app/recs/feed_rank.py`; no I/O, no LLM; DESIGN §17.2)
- `read_first(new, item_ids, graph, reader, now) -> tuple[str, ...]`: for each new concept, its
  graph prerequisites that are themselves new to the reader (`is_new`) and not among the item's
  own concepts; deduped; ordered by `base_difficulty` then label; at most `READ_FIRST_MAX` = 2.
- `readiness_level(new_count, read_first) -> "familiar" | "ready" | "stretch"`: 0 → familiar;
  any read-first or new_count > `READY_MAX` (4) → stretch; else ready.
- `RankedItem` gains `readiness` and `read_first`; `rank` computes them with the `new` list it
  already has. **Ranking scores are unchanged** (the existing `readiness()` factor stays as is).
- `FeedItemOut` gains `readiness` (default "ready" for older clients) and `read_first`
  (list[str], default empty). Demo snapshots are re-ranked against the served graph at request
  time (`snapshot_candidates` → `rank`), so they get both with no stored change.
- Up next and library rows are not touched (Up next and the library's Topics rows are in the
  web main bundle, which has 0.04 KB left).

## Web (`ForYouTab`, its lazy chunk only)
- `lib/feedApi.ts`: `readiness?` and `read_first?` on `FeedItem`.
- A pure helper `readinessLine(item)` in a chunk-only module (`lib/readiness.ts`, imported only by
  ForYouTab) returns the text; ForYouTab passes it through Row's existing `why` slot after the
  goal line. No new CSS in main; if a class is needed it goes in the For you chunk's CSS.
- Bundle: main must not change (149.96 KB); ForYouTab chunk measured before and after.

## Tests (first)
- API: `read_first` (prerequisite new → listed; known → not; the item's own concept → not;
  dedupe; cap 2; most basic first; a concept with no prerequisites); `readiness_level` (0, 1, 4,
  5, read-first present); `rank` carries both and the score is identical to before (a test pins a
  score from the current code); the feed route returns both; a demo snapshot gets them.
- Web: `readinessLine` for each level, with and without read-first, with a goal; ForYouTab renders
  the line in the row; an older API (fields absent) shows nothing new.

## Acceptance
1. Suites (API pytest + ruff, `pnpm -r typecheck`, `pnpm -r test`); main bundle unchanged.
2. Emulator harness, no model call: the demo reader's For you (newcomer persona, a live snapshot
   feed from the emulator) at 1440 and 390, light and dark: every row has a readiness line; axe 0;
   no horizontal scroll; at least one row of two different levels, or the report says which
   levels the snapshot produced. Shots in `docs/evidence/readiness/`.
3. milestone-reviewer SHIP → PR → CI → merge → deploy API, then web (Sourabh's yes on each) →
   live: a demo reader sees the lines.

## Production writes
The two deploys; the live check's demo user (written, then deleted by End demo: W2); the mix
script reads only (W1).

## Docs
DESIGN §17.2 (the line and its rule), STATUS decision 60, §1 row, a short acceptance section.

## Round 1 (plan-reviewer REVISE, 14 items; applied, these override the sections above)

**V1. Signature.** `rank(candidates, reader, now, graph)` (graph passed in; call sites
`feed_router.py` and `tests/test_feed_rank.py`). `read_first(new: Sequence[Concept], item_ids:
frozenset[str], graph, reader, now)`; the labels tuple stays separate.
**V2. No line without named concepts.** An item that names no graph concept gets `readiness =
None` (no line). `readiness_level(named_count, new_count, read_first)`.
**V3. Exact strings.** familiar: "Mostly familiar"; ready: "Ready for you"; stretch with two
read-first: "A stretch: read up on X and Y first"; with one: "A stretch: read up on X first";
with none (more than 4 new ideas): "A stretch: many new ideas at once".
**V4. The map's rule.** `is_new` is the map's not-known (p < `KNOWN_P` 0.5, `reader/overview.py`).
"Ready" = every new idea's prerequisites are known, as the map's "ready to learn"; the one
difference, stated in DESIGN §17.2: a new idea with no prerequisites in the graph counts as ready
here but gets no ring on the map.
**V5. Basis said.** The line carries `title="Based on the ideas named in the title and summary"`
(For you chunk only) and DESIGN §17.2 says the same.
**V6. Fields.** `readiness: Literal["familiar", "ready", "stretch"] | None = None`,
`read_first: list[str] = []`; TS union to match; absent or null → no line.
**V7. Mix first.** Before the web work, a pure test over the committed demo snapshot fixture counts
levels for all three personas (no network); counts in the report. If one level is ≥ 80% of the
newcomer's rows, stop and tell Sourabh (no threshold retuning). Re-run after the Oct 16 re-seed.
**V8. Harness.** `tools/shots/readiness.py`: writes `persona_feeds/newcomer` into the emulator from
a committed fixture, opens For you as the demo reader; asserts zero search and zero model calls.
**V9. Goal + readiness test.** ForYouTab render test: goal first, then readiness, in one
`.row__why`; nothing in the meta line.
**V10. Rank tests.** A new prerequisite also named by the item: not listed, still counted; a
prerequisite id missing from the graph: no crash; `select` and `_out` carry both fields.
**V11. Production writes.** The deploys; the live check makes 1 anonymous user and 1
`rec_signals/newcomer` doc (deleted by End demo: W2).
**V12. Deploys** from clean, up-to-date `main` after `make check-gcp`, API before web.
**V13. Live evidence.** Production `/v1/feed` level counts per persona and one live shot in
`docs/evidence/readiness/`, in the STATUS section.
**V14. Schedule and wording.** STATUS §9 Oct 15 row with a checkpoint (not merged by end of Oct 15
IST → ask Sourabh what to cut, decision 27) and decision 60 recorded before coding: shown as three
levels, not a number (a number from title and summary matches would be false precision); Sourabh
asked in one line before the web work.

## Round 2 (plan-reviewer REVISE, 2 items; applied)

**W1 (V7).** The mix is measured by a read-only script, `scripts/readiness_mix.py`: after `make
check-gcp`, it reads the 3 production `persona_feeds/{persona}` docs, the 3 `persona_templates`
and the served graph from Cloud Storage, runs `snapshot_candidates`, `rank` and `select` in memory
and prints level counts per persona; it writes nothing. Run before the web work and again after
the Oct 16 re-seed. Stop rule unchanged (one level ≥ 80% of the newcomer's rows → tell Sourabh,
no retuning). A small handmade fixture test stays for correctness only. Production: reads only.
**W2 (V11).** The live check ends with "End demo" (delete on request); the STATUS section records
that the anonymous Auth user and `users/{uid}` (with `rec_signals/newcomer`) are gone. Expected:
1 anonymous user, its `users/{uid}` and `rec_signals/newcomer` written, then all deleted.

**Nit taken:** the mix script prints each persona template's `graph_version` beside the served graph's.
