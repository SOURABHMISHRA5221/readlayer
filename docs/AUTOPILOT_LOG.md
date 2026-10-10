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
