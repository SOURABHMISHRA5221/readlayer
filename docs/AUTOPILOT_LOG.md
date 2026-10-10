# Autopilot log

Running record of the autopilot run that began 2026-10-10: decisions, reviewer verdicts, what
changed, live URLs and numbers. Newest entries at the bottom of each milestone.

## Ground rules for this run (confirmed by Sourabh, 2026-10-10)

- Order: rest of M6 (A two-phase ingest, B annotator, C web, D shared restatement), M7 (knowledge
  map and edit-by-prompt **required**), M8-local, M2.2, M9 hardening. Nothing is cut without
  asking; if late, stop and ask what to cut.
- Per milestone: plan → plan-reviewer loop until APPROVE (replaces plan mode and plan approval) →
  implement on a milestone branch with tests and a design critique (desktop, mobile, dark) for UI →
  milestone-reviewer until SHIP → merge when CI is green → deploy from up-to-date `main` → live
  checks → STATUS.md → next.
- Pre-approved: CLAUDE.md edits for the split explanation cache key and the new working agreement;
  the TTL policy on `pending_contents.expire_at`; production writes within the counts each plan
  lists; merging a PR once CI is green and milestone-reviewer says SHIP.
- Still needs Sourabh: every deploy and `git push` (permission prompt), production writes beyond
  the plan's counts, raising any budget or cap, product decisions the docs don't settle.

---

## M6 (rest)

### Plan
- 2026-10-10: plan drafted (`~/.claude/plans/frolicking-hatching-fairy.md`): A two-phase ingest,
  B annotator (markers, prompt chip, pre-read, events), C web, D shared restatement.
- plan-reviewer round 1: **REVISE**, 16 items (lease vs analyse timeout, pending URLs on other
  entry points, paragraph identity, attempts semantics, deploy compatibility, named production
  writes, dwell word overcount, dismissed span-only, text_searched scope, restate route and prompt
  hygiene, eval runner integrity + background suite, split outcomes/latency/caps, CLAUDE.md and
  STATUS docs, acceptance wording and 5 s target, copied text excluding UI, order within the day).
  All applied.
- plan-reviewer round 2: **APPROVE**; three optional nits applied (paragraph marker isn't a mark
  for text_searched; cite the shipped explain-v3 eval row as "before"; deploy after each PR).
- Sourabh: start now, work A → D straight through.

### Build
- A (API): two-phase ingest. `fetch_and_extract` (phase 1, no LLM) stores
  `pending_contents/{id}`; `analyse_pending` (phase 2) takes a 150 s lease in a transaction, runs
  under `asyncio.timeout(ANALYSE_TIMEOUT_S=120)`, writes `contents/`, deletes the pending doc.
  POST /v1/recs/open = phase 1 only (`ready: false`); new POST /v1/content/{id}/analyse (200 ready,
  202 busy lease, 410 after 3 counted failures, 504 timeout); GET /v1/content/{id} serves pending
  docs with `status: "analysing"`; annotations/recommendations 409 while pending. Pending URLs
  count as known (no fetch, no quota) on both entry points. `text_searched` accepted with
  `paragraph_id` only (offset, no evidence). 11 new tests; 431 pass.
- Deviation: the plan's new 400 KB extracted-text refusal was not added: `clean_paragraphs`
  already truncates at 150,000 characters (`MAX_ARTICLE_CHARS`), which is tighter.
- Cancellation (client went away) releases the lease without counting an attempt; only analyses
  that ran and failed (model errors, linking errors, timeout) count.
- B (annotator 0.4.0): paragraph markers (pilcrow in the margin, float right below 900 px),
  "Know this?" chip with `onAnswer`, `renderPreread`, reading signals (`paragraph_dwell` with words
  on the first dwell only, `text_searched` concept or unmarked-paragraph only, never text),
  `annotation_dismissed` for deliberately opened span cards closed without an action, copies
  across the chip give back only article text, Helpful has a text label. Inserted controls carry
  `data-rl-ui`; `indexText` skips them so anchors never shift. 13 new vitest (incl. axe-core);
  36 pass.
- C (web): events carry paragraph_id/words/ms, flush on hide and pagehide (annotator.flush first),
  one retry per failed batch; pre-read slot; prompt answers → PATCH /v1/me/graph; paragraph
  explanations by `paragraph_id`; two-phase load ("Preparing your notes… N s", analyse with 202
  retry for up to 180 s, missing `status` = ready). Bundle 136 KB gzip (budget 150).
- Fix found by axe in the live page: rail chips faded to 0.28 under an open sidenote failed
  contrast (pre-existing since M5); they now hide while a card is open. axe in the live reader:
  0 violations (light 1440, dark 1440, light 390).
- Design critique (headless Chrome, 1440 light/dark, 820, 390 light/dark): pre-read steps without
  a link had no expand affordance → chevron added. Tablet popover overlaps the paragraph it
  explains (same as span popovers): accepted.
- Acceptance (local, API on prod Firestore):
  1. Newcomer on "Government extends RoDTEP…" (1bff839e…): pre-read 3 steps, 2 markers, prompt
     on SEZ. Keyboard only: marker Enter → focus in card → Tab → Escape returns focus to marker;
     Tab reaches chip buttons. "Not really" on SEZ → PATCH 200 → reload: SEZ is now a span, the
     prompt slot moved to "Export Oriented Units". PASS.
  2. "Open here" on a new URL: article visible **1.39 s** after the click, notes **24.7 s**, no
     reload; pending doc deleted, contents doc stored (9 paragraphs, 9 demands, 7 linked,
     $0.0024). PASS.
  3. One 5 s batch carried paragraph_dwell ×5, text_searched (unmarked paragraph),
     explain_opened, annotation_dismissed; replaying it returned `events_applied: 0`. PASS.
- Production writes so far: https://en.wikipedia.org/wiki/Term_premium returned 404 (no such
  article; refused in phase 1, slot refunded, nothing stored), so the local test used
  https://en.wikipedia.org/wiki/Yield_curve_control instead (same count: 1 `contents/` doc,
  `user_ingested`; checked not in corpus or held-out lists; dry run first). `ops/ingest` +1.
  Two anonymous test sessions (automation tab + headless profile) exist; deleted at the end of
  local testing.
- Automation note: the Claude-in-Chrome tab reports `visibilityState: hidden`, so
  IntersectionObserver never fires there; dwell and timing checks ran in headless Chrome over CDP.
