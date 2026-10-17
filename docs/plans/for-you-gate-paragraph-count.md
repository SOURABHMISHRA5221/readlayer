# "For you" after 10 articles; paragraph notes counted; explain a selection (decision 70)

Sourabh, 2026-10-17 evening, two small fixes on the live site:
- **Fix 1.** "lets remove the For You in side card ... our intial graph takes lot of assumption and
  for you becomes more like Policy/ and Finance and thus first infrence is not good For you should
  only come after 10 articles consumption". Asked the rule, and whether demo personas keep it; he
  answered "lets remove for you and mention Your Pick "Software" only as For u..." (cut off). Read
  as: until the reader has engaged with 10 articles there is no toggle and the card names the pick,
  "Your pick · Software"; from 10 the toggle returns. Personas follow the same rule (he chose
  removal; nothing exempts them). Stated back to him before planning.
- **Fix 2.** "we get P to re check a paragraph but we still say 1 notes or 0 notes those should be
  the mentioned to as that makes user feel somthing is done on this para". Asked: count and list
  the ¶ notes, or hide a zero count. He chose: **"this"** — count and list them ("a page with two ¶
  notes and one word says 3 notes for you").

Past the 18:00 last-feature-deploy line; Sourabh asked for both ("add both changess"). PR A,
`d70-small-fixes` (Fixes 1–2): tests first → milestone-reviewer → PR → CI → merge → `make deploy-api` (yes) →
`make deploy-web` (yes) → live check. Both deploys run from an up-to-date, clean `main` at the
merge commit, never from `d70-small-fixes`. PR B (Fix 3) follows the same pipeline, branched from a
clean `main` after A's merge. Then the `/v2` removal, gitleaks, deck link, submit.

- **Fix 3** (added 19:50): "also make user select any words or phase to get analogy cards". Offered
  a cheap version (match the selection to a term already extracted on the page and open its card;
  else the paragraph's card; no new model path) against a fresh card for any phrase (a new model
  path through the verifier: too risky tonight). He said: **"Add that change"**.

- **Fix 4** (added 20:10, PR A): "change article to content on Landing page as article is more
  towaords reading and content is neutral". Generic uses only: "Try it on any article" → "Try it on
  any content" (hero card and mini demo), "checked against the article" → "checked against the
  content" (hero proof line); the static hero in `index.html` regenerated (`UPDATE_HERO=1`). Kept,
  as they name a real article: the "Articles" format chip, the Economic Times screenshot caption
  and alt texts, the extension's "Open a news article" step; `/v2` untouched (removed before
  submitting).

**Two PRs (plan review round 2).** PR A `d70-small-fixes`: Fixes 1–2 → merge → deploy → live check.
PR B `d70-select`: Fix 3, started only after PR A is live-checked, same pipeline. **Cut-off for PR B:
23:00 IST**: not merged by then → dropped, recorded in STATUS, Sourabh told; submission never
waits for it.

**Fix 1 reading and the demo counts:** stated back to Sourabh twice (the rule, personas included;
the new counts below); he answered with further requests and no correction ("Add that change").
Proceeding on that reading; called out again in the PR summary.

**Demo counts (read-only, 2026-10-17 19:40 IST; one anonymous demo reader, `GET` annotations
only, deleted after, 204).** Spans + ¶ = what the margin will say:
- Guardian Polymarket (`99a2cb53…`): newcomer 10 + 6 = **16**, trader 4 + 2 = **6**, policy
  student 8 + 5 = 13.
- Mint Sebi (`d530bb6b…`): newcomer 11 + 5 = **16**, trader 1 + 1 = **2** (the recording sheet's
  "trader 0" is already 1 today, before this change), policy student 11 + 5 = 16.
- Videos (NSE vs BSE, DW Nobel) aren't in the article list the counter searched; checked in the
  live check after the deploy.
`docs/recording.md` updated with these counts in this PR.

## What is true today (read from code)

- `app/reader/frames.py::for_you` offers a frame as soon as one domain has 3 known concepts in the
  reader's edges. A new account's onboarding answers (Quick check, home country, field) are edges,
  so "For you" shows on the first article, usually Policy or Finance.
- The card (`packages/annotator/src/card.ts::fillFrames`) shows the two-option toggle only when
  `frames.for_you` is set and differs from the pick; otherwise it shows a small "Analogy · X"
  label from `analogy_domain` when the Background used one.
- `ReaderState.engaged` (content id → last engaged, newest 50 kept, never windowed when stored) is
  filled by `reader/events.py` from any applied event with a content id: `paragraph_dwell`
  (time on a paragraph), `article_helpful`, `text_searched` on a paragraph, and every concept event
  (opened, knew this, helpful, …). This is the "consumed" data the state already has.
- The web counts notes from `UpdateResult.resolved`, which lists **span** ids only. Placed ¶
  markers are never reported, so the margin heading (`ConceptRail`, "N notes for you"), the drawer
  (`ConceptDrawer`, hidden at 0) and the left rail (`ReadingSpine`, hidden at 0) ignore them; a
  page with only ¶ markers says "0 notes for you" in the margin. The plural is already right
  ("1 note"); no "1 notes" string exists in code.

## Fix 1: the "For you" gate

**Rule.** `frames.for_you` returns None unless `len(state.engaged) >= MIN_ARTICLES` (10): ten
distinct pieces (articles, videos or podcasts) the reader has engaged with as defined above. The
stored map caps at 50, so once reached it never drops back. No new data, no new Firestore field.
Same rule for signed-in readers and demo personas (a persona's demo session has its own `engaged`,
empty until that session reads).

**API** (`app/reader/frames.py`): add `MIN_ARTICLES = 10` and the check first in `for_you`;
docstring updated. `explain/router.py` unchanged: with `for_you` None the response already says
`frames.for_you: null, used: "pick"`, and a `frame: "for_you"` request serves the pick (existing
test). No prompt or cache-key change (Background keys are by frame; nothing new is generated).

**Card** (`card.ts`): when there is no toggle and the Background is shown with an analogy, the label
names the pick if the card used it (any time `frames.pick` is set and `frames.used === "pick"`,
whether or not the host enabled the toggle; the extension sends no `frames`, so it keeps today's label): `Your pick · Software` (capitalised `frames.pick`) instead of
`Analogy · software`. Falls back to today's `Analogy · X` when `frames` is absent or `pick` is
null (hosts that don't send frames, e.g. the landing demo). Shown under the same condition as today
(a verified Background with an `analogy_domain`), so the card never claims an analogy it didn't use.

**Warm-up script.** `warm_demo`'s for_you pass now gets the pick back for personas (cache hits, no
new generations); it is not run again for this change. Left as is; noted in STATUS.

**Tests first.**
- `test_frames.py`: `test_for_you_needs_ten_engaged_articles` — a state with a qualifying finance
  map and 9 engaged contents → None; 10 → "finance". Existing tests get a 10-article `engaged` in
  their `state()` helper default so they keep testing ranking.
- `test_explain_api.py`: through the API with the real `for_you` (no monkeypatch), a reader with
  a qualifying map and 9 engaged → `frames.for_you` null; 10 → set.
- `packages/annotator/test/nextup.test.ts` (where the frame toggle is tested): frames `{pick: "software", for_you: null, used: "pick"}` with an analogy → no
  radiogroup, label "Your pick · Software"; with for_you set → toggle as today; no frames →
  "Analogy · …". The existing "no toggle without loadFramed" test's expected label changes from
  "Analogy · cricket" to "Your pick · Cricket".

## Fix 2: ¶ notes counted and listed

**Annotator** (`packages/annotator/src/index.ts`): `UpdateResult` gains `paragraphs: string[]` —
placed marker ids in document order (by their paragraph's position). Additive; the extension
ignores it. `open(id)` already opens a marker's card.

**Web.**
- New pure `apps/web/src/lib/notes.ts::pageNotes(spans, markers, paragraphs)`: merges span notes and
  placed ¶ notes in document order (a ¶ note sits at its paragraph's start, before that
  paragraph's spans). Each ¶ note is the annotator's `paragraphCard` (now exported) with label
  `Paragraph N` (N = its 1-based position in `article.paragraphs`).
- `useAnnotator` keeps `paragraphs` from the result next to `resolved`.
- `ReaderPage`: `notes = pageNotes(...)` feeds the margin (`ConceptRail`), the drawer and the left
  rail; `EndBlock`/Recap "new concepts" stay spans only (they are about concepts).
- `ConceptRail` and the drawer: heading counts all notes ("3 notes for you"); a ¶ item reads
  "Paragraph 4, what it's saying" with a ¶ glyph in place of the dot (`data-kind="paragraph"`),
  and opens that paragraph's card. Hover highlight is a no-op for ¶ items (markers have no mark).
- `ReadingSpine`: count includes ¶ notes; ticks for ¶ notes at their paragraph start
  (`SpineNote` gains `kind`; `SpineTick.level` gains "paragraph", drawn hollow).
- Sub-line under the rail heading unchanged.

**Tests first.**
- `apps/web/test/pageNotes.test.tsx`: `pageNotes`: two ¶ notes + one span → 3 notes in document order, ¶ before the span in the
  same paragraph, labels "Paragraph N"; only ¶ notes → count 2 (not 0).
- same file, `ConceptRail` rendered: heading "3 notes for you" with two ¶ and one span; ¶ item text and click →
  `onOpen(markerId)`.
- `packages/annotator/test/mount.test.ts`: `update()` returns `paragraphs` with placed marker ids in order and
  omits a marker whose paragraph is missing.
- `apps/web/test/spine.test.ts`: a ¶ note's tick at its paragraph start.

## Fix 3: explain a selection (cheap version)

**What the reader gets.** On the web reader, selecting a word or phrase inside one paragraph shows a
small "Explain" button by the selection. Pressing it opens a card:
1. If the selection overlaps a term extracted on this page (any demand in that paragraph with a
   concept, shown or not), that term's card — the usual verified Background (in the reader's
   frame, so with an analogy when the Background has one) and "What the author is saying". If the
   term is already marked on the page (same demand, or the same concept elsewhere), that mark's
   card opens instead; no second mark.
2. Otherwise the paragraph's card ("What this paragraph is saying"), adding its ¶ marker if absent.
A looked-up term becomes a marked note on the page for this view (counted by Fix 2). No new model
path: both cards come from `/v1/explain` (demand or paragraph mode) with its verifier, cache, daily
caps and rate limit. Extension and landing: not in this PR.

**API.** `POST /v1/content/{id}/lookup` with body `{paragraph_id, start, end}`: offsets within the
paragraph's text, never the text itself (Cloud Run's request log records URLs; CLAUDE.md: logs
never carry article text; DESIGN §8). Checks: paragraph exists (404), `0 <= start`,
`end <= len(para.text)`, `2 <= end - start <= 120` (422). `ratelimit.annotations`; `doc_or_error`
for access → `{annotation: AnnotationOut | null}`. Pure `scorer.lookup(doc, scored, paragraph_id,
start, end)` over `score_demands(...)` (same inputs as `score_for`): demands in that paragraph with
a concept, each placed with `locate(para.text, anchor.exact, anchor.prefix)` as `span_inputs`
does, whose range overlaps `[start, end)`; prefer one contained in the selection, then longest,
then score, then reading order; built with the existing `_span`. Nothing recorded; the log carries
the paragraph id and hit/miss only; nothing reaches a model (only the demand or paragraph id goes
on to `/v1/explain`).

**Annotator** (new `packages/annotator/src/select.ts`, option `onSelectionExplain(sel:
{paragraph_id, start, end})`): on `pointerup`/`keyup` inside the root, a non-collapsed selection within
one `[data-rl-paragraph]` element, not inside our UI, 2–120 chars, shows one button
(`rl-select`, `UI_ATTR`, fixed under the selection's last rect, kept on screen); also a debounced
`selectionchange` listener (touch handles fire neither pointerup nor keyup); hidden on collapse,
scroll, Escape, or opening a card. The host gets `{paragraph_id, start, end}` computed with
`indexText(scope)` as `locate()` does (skips ¶ markers and our controls). Off unless the host passes the option. Keyboard:
the button is reachable with Tab right after the selection and has the label "Explain this".
Reduced motion respected. The copy/right-click `text_searched` signal is unchanged.

**Web** (`useAnnotator`, `ReaderPage`, `lib/api.ts`): `api.lookup(...)`; the hook keeps this
view's asked notes (cleared on a new article, persona or density), merges them into what it
passes to `update()`, and opens the asked id (focus into the card) once placed; if the asked id
comes back in `unresolved` (it overlaps another mark), it is dropped and the paragraph card opens. On a lookup error
it falls back to the paragraph card. The hook exposes the asked notes so `ReaderPage` counts and
lists them with the rest.

**Tests first.**
- `apps/api/tests/test_lookup.py`: `scorer.lookup` — exact term, phrase containing the term,
  selection inside a longer term, the longest contained wins, another paragraph's demand never
  matches, a demand without concept never matches, no overlap → None (even when the selected
  text appears inside a term elsewhere in the paragraph), only the overlapped occurrence of a
  repeated term matches. Route: 200 with the annotation; no match → `{annotation: null}`; unknown
  paragraph → 404; out of bounds, 1 char, 121 chars → 422; persona works; nothing written.
- `packages/annotator/test/select.test.ts`: a selection in one paragraph shows the button; across
  two paragraphs, inside the card, or 1 char → none; click calls the host with the paragraph id
  and offsets (never text) and hides the button; a selection after a ¶ marker gives offsets in the
  paragraph's own text (our controls skipped); Escape hides it; no option → no button.
- `apps/web/test/selectionLookup.test.tsx`: a hit not on the page is added and opened; a hit whose
  concept is already marked opens the existing mark; no hit → the paragraph card; error → the
  paragraph card; a hit that comes back unresolved → dropped, the paragraph card.

## Acceptance

1. API tests, web tests, annotator tests, `pnpm -r typecheck`, ruff: all green.
2. Harness/local: a fresh reader (0 engaged) opens a note → no toggle, "Your pick · Software";
   after 10 engaged (seeded in the emulator) → toggle back.
3. A page with ¶ markers: margin heading counts them, items open their card; bundle stays in budget.
4. Live (after both deploys): first read Sourabh's `engaged` size (read-only). Below 10: no toggle,
   "Your pick · <his pick>"; 10 or more: the toggle (or "Your pick" alone if for-you equals his
   pick). A page with ¶ markers says the right count.
5. Live, persona (what judges see): the trader on the Guardian article (`99a2cb53…`) shows no
   radiogroup and reads "Your pick · Cricket"; the margin says 6 notes. One demo reader, deleted
   after; no other production writes.
6. The demo counts above re-read after deploy match the margin; the videos' counts recorded.
7. Selection, local and live (one demo reader, deleted after): on the Guardian article as the
   trader, select "insider trading" (extracted, not marked for the trader) → its card opens with a
   verified Background; select a plain phrase with no term → the paragraph card; keyboard path
   works; the margin count goes up by one for the added note; a 375 px pass in the bottom-sheet
   mode (touch selection). Cost: at most a few explain calls. PR B only; if dropped at 23:00, this
   check is recorded as not done.

## Docs in PR A

- DESIGN §7 "Analogy frames": the `len(engaged) >= 10` gate (personas included) and the no-toggle
  "Your pick · X" label with its "Analogy · X" fallback.
- DESIGN §9 Reader: the margin's "N notes for you" counts and lists placed ¶ notes ("Paragraph N,
  what it's saying"); the spine shows ¶ ticks.
- STATUS: §10 row 70 with Sourabh's quotes, §37 (or §38) rows, §9 note that decision 69's live
  check "the card toggle reads 'For you'" no longer applies to personas or new accounts; Last
  updated line.
- `docs/recording.md`: the new counts. `docs/AUTOPILOT_LOG.md`: an entry.

PR A's docs cover Fixes 1–2 only.

## Docs in PR B

- DESIGN: a new "Explain a selection" bullet (§9 Reader) and the `/lookup` row in the API table;
  §8's selection line updated (offsets only, never the text).
- STATUS (§10 row 70 addendum, acceptance rows) and `docs/AUTOPILOT_LOG.md` for Fix 3. If B is
  dropped at 23:00, STATUS records that instead.

## Not doing

No fresh card for an arbitrary phrase with no extracted term (a new model path), no selection in
the extension or the landing demo. No new "consumed" signal (read-to-end), no settings flag for the threshold, no extension change
(it shows no count), no landing change.
