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
- D (shared restatement): `restate` (restate-v1) + `explain` (explain-v4, Background only) +
  `verify` (verify-v2, claims) + `verify_background` (verify-background-v1); two cache entries per
  card (restatement by span+style, shared; Background by span+band+frame+style); parts run in
  parallel; a request counts once against the explain caps; past the cap a shared restatement
  still shows; "This is wrong" evicts both parts. Deviation from the plan: the Background judge
  is a separate prompt and route (`verify_background`) rather than a second verdict in
  `verify.md`; `verify` still bumped (v2, claims only).
- Eval integrity: 5-case Background suite + runner change committed (fd30bba) before the run.
  Run `explain-v4-split`: adversarial 15/15 (judge 15, was 14), good 25/25, Background 5/5,
  pipeline 24/1/0, injection 10/10; $0.0090 per card from scratch (was $0.0070), p50 9.6 s (was
  14.9 s), p95 31.4 s (was 21.8 s). Eval spend $0.46.
- Acceptance 4 (local): newcomer then trader on RoDTEP: 3 restatements for 3 distinct spans,
  4 Backgrounds; "RoDTEP rates" restatement made once and reused by the trader. PASS.
- CLAUDE.md: split cache keys and the autopilot working agreement (pre-approved).
- Cleanup and an incident: test sessions deleted via DELETE /v1/me (headless b64c5fd4… 204).
  The automation-tab session (115f6c76…) had already been ended at 06:42:49 UTC, not by me. At
  06:58 UTC a different anonymous session (47fc3fc4…) used that visible tab (library → "Nifty 50
  correction" → 3 explanations); I deleted it at 07:02:41 believing it was my test session. It was
  an anonymous demo session I did not create (events, counters and its anonymous Auth user);
  shared content untouched. Reported to Sourabh. Rule for the rest of the run: only delete
  sessions whose uid_hash I created in the same step, verified against the log first.
- Resolved: Sourabh confirmed the 06:58 UTC (12:28 IST) session in the automation tab was his;
  no harm done. The cleanup rule above stays for the rest of the run.
- Live check script drafted (`scripts/live_check_m6.py`) and dry-run against the local API: all
  four checks pass (annotations kinds, event replay 4 → 0, prompt answer changes the next load,
  shared restatement with distinct Backgrounds); its test user deleted (204).
- milestone-reviewer round 1: **FIX** (4 blocking, 2 should-fix). Applied:
  1. live check script and log committed;
  2. eval report counted only `verify` as a judge: now both judges, averaged per call
     (2.00 calls, $0.0039 judge per card), report regenerated from the same result file;
  3. STATUS: next actions rewritten, M6 costs added, `pending_contents` TTL marked pending,
     "Open here" 1.4 s marked local, deviations recorded (one PR/deploy, axe instead of
     Lighthouse, two keyboard checks covered offline);
  4. the 07:02 deletion did not end the session: after a dev-server restart (in-memory
     revocation lost) it sent one event batch at 07:10:19 (200). Read-only check: `users/{uid}`
     + 6 events + 1 `demo_graphs/newcomer` = 8 docs under a deleted Auth user (Sourabh's
     session). Not deleted (beyond the plan's writes); left for the M9 anonymous cleanup unless
     Sourabh says otherwise. Noted in STATUS §5;
  5. per-part single-flight (`_inflight` keyed by each part's cache key) so two personas loading
     cold share one restatement; new concurrent test;
  6. POST /v1/content always adds the doc to the catalog (a pending URL is new to it too).
- milestone-reviewer round 2: **SHIP**. Follow-ups applied: DESIGN §7 says single-flight per
  part; the eval report's latency column is labelled "Claims judge".

### Ship
- PR #14 squash-merged (25210ca) after CI green (api, typescript) and milestone-reviewer SHIP.
- Deployed from up-to-date `main`: API `readlayer-api-00011-6sp`, then web `index-DKVIFx4G.js`
  (Sourabh approved both prompts). TTL on `pending_contents.expire_at`: ACTIVE.
- Live: `live_check_m6.py` all 4 pass; "Open here" on Quantitative tightening: article 7.31 s
  (over the 5 s warm target; cold first ingest on the new revision, shared instance), notes
  22.5 s, no reload, pending deleted, contents 311; demo articles re-warmed (24/24 hits on the
  second pass, slowest 598 ms); axe 0 violations ×3; console 0 errors. Every test session made
  here deleted (204).
- Deviation: the live "Open here" was opened with the page's own token, not by clicking an Up
  next card (Up next can't be made to offer a chosen URL); the reader's two-phase flow is the same.
- Open for Sourabh: (a) one more new URL to measure the warm live "Open here" time (a production
  write beyond the plan's count); (b) delete the 8 orphaned docs from his 12:28 session now, or
  leave them for the M9 cleanup.

---

## M7

### Plan
- 2026-10-10: BUILD_PLAN.md M7 section updated at Sourabh's request (knowledge map and
  edit-by-prompt required; "first to cut" line and the automatic cut order removed). Committed
  with the plan.
- Plan drafted: `docs/plans/M7.md` (consent, onboarding, calibration, profile page with Cytoscape
  map and list view, edit-by-prompt, emulator-based local e2e harness).
- Calls made where the docs don't settle it (flagged for Sourabh, plan proceeds unless he says
  otherwise): (1) edit-by-prompt is for Google readers only; demo personas see it disabled;
  (2) onboarding's "liked links" are picked from the library instead of pasted URLs (no ingest,
  no cost, no SSRF surface at sign-up).
- plan-reviewer round 1: **REVISE**, 11 items (budget guard under the emulator, emulator env
  refused on Cloud Run + seed script can't write production, name cap 30 and ≤ 3 link_confirm
  batches, demo variant for edit-by-prompt is Sourabh's call before step C, persona frames on the
  demo profile, consent gate in the API, new rules and deviations recorded, live Google acceptance
  as a named step, React.lazy routes + cytoscape in dependencies, no reader-typed strings stored,
  eval before/after in report.md). All applied, plus 2 nits.
- plan-reviewer round 2: **APPROVE**; 3 optional nits applied (rec_signals under the consent gate
  and export/delete always open; edit box follows the variant; demo undo skips dropped edges).
- Asked Sourabh: edit-by-prompt for demo readers (variant B) or Google only (A); one more live URL
  for a warm "Open here" measurement; delete the 8 orphan docs now or leave for M9. Work proceeds
  on A, B, D, E, G meanwhile; C waits for the answer.

### Build
- A (API): POST /v1/me/consent (`consent-v1`), POST /v1/onboarding (θ from comfort, interest,
  frames, liked library articles → +0.2 nudges, ≤ 15 salient concepts each), GET
  /v1/calibration/next (round-robin over interest domains, b closest to θ among the 150 most
  frequent concepts, deterministic), POST /v1/calibration/answer (only the current item; explain
  +3.0 / heard −1.5 / none −3.0, Elo K 0.3), POST /v1/calibration/skip; profile `onboarding`
  block. Consent gate: events, page-view writes, rec signals and served items record nothing for
  a Google reader without consent; corrections and settings 403; export/delete always open.
  Demo profile shows the persona's frame. Existing signed-in test readers now consent first.
- B (API): map nodes carry `recent` (last 3 evidence items, newest first).
- Tests: 10 new (onboarding); API suite 451 pass.
- Sourabh decided C1: edit-by-prompt **for demo accounts too, session-scoped**: edits apply to
  that demo session's copy of the persona only and reset to the original afterwards (new
  session; End demo deletes it). Added a "Reset persona" button (POST /v1/me/demo/reset) so a
  demo reader can return to the original within the session, and session-only frames for demo
  `set_thinks_in`. Plan updated.
- Harness groundwork: Settings refuse `FIREBASE_AUTH_EMULATOR_HOST` / `FIRESTORE_EMULATOR_HOST` on
  Cloud Run or ENV=prod (tests); `FIRESTORE_PROJECT` / `db_project` so Firestore can point at the
  emulator's demo project while Vertex and GCS keep the real project.
- G (harness): `make dev-emulator` (apps/api/scripts/dev_emulator.sh): Firestore + Auth
  emulators (demo-readlayer), `seed_emulator.py` copies 5 articles, 3 persona templates and
  today's spend ledger read-only from production (two explicit clients; refuses same target),
  harness budget = min($1, $8 − today's production spend), API with emulator hosts and
  `FIRESTORE_PROJECT=demo-readlayer`, web with `VITE_USE_EMULATORS=1` (window hook for an
  unsigned emulator Google identity; the Vite build refuses emulator mode). Smoke: emulator
  "Google" reader → API 200, onboarding step "consent". First run: production spend today
  $0.82, harness budget $1.00.
- Profile-edit evals: v1 schema rejected by Vertex (0/6, 0/4 at $0; tagged unions and an outer
  maxItems are refused); flat schema + local strict whitelist; v2 5/6 · 4/4; v3 (domain-work rule)
  6/6 · 4/4, $0.0049. Cases unchanged (decision 26); before/after in evals/report.md + changelog.
- D+E+F (web): `/welcome` (consent-v1 → field → interests → comfort → frames → liked library
  articles → 8-tap calibration with Skip; focus moves to each step's heading) and `/profile`
  (summary, ability/interest bars with numbers as text, knowledge map: Cytoscape + dagre in a
  lazy chunk, list view grouped by depth (default below 640 px), search, node card as a native
  modal dialog with last 3 evidence items and corrections; this week + trend table; analogy
  chips (read-only for demo personas); preferences; edit box with preview/apply/undo and demo
  reset; data controls with export, delete/end demo, pause). Onboarding gate for Google
  readers; React.lazy route chunks; account menu links to the profile. Segmented control is now
  reachable by keyboard with nothing selected. Bundle: main 137.6 KB gzip (budget 150),
  ProfilePage 6.7 KB, WelcomePage 3.3 KB, cytoscape 121.6 KB + dagre 33.6 KB only when the map
  opens. Web vitest added (4 helper tests).
- Acceptance on the emulator harness (all pass): different spans (UK bonds 8 vs 2, Polymarket 9
  vs 4) and analogies (software vs cricket); delete → sign-in → consent; profile keyboard dialog
  with focus return; axe 0 at 1440 light/dark, 390, 320 and on the welcome steps; no overflow at
  320 (topic toggle now wraps); 44 px targets; acceptance sentence previews options/short and,
  after Apply, the next explanation is a miss at 23 words vs 56. Fixes found on the way: Firestore
  transaction contention under three prefetches (jittered retry), Escape focus return, preview
  showing unchanged settings, "−0.0 · building" wording, bar alignment.
- Harness spend $0.07 (separate ledger seeded with production's $0.82).
- `scripts/live_check_m7.py` (demo side of M7: persona profile/frame, map evidence, session-only
  edit preview/apply/undo/reset, onboarding refused for demo readers); dry-run on the harness
  with `--emulator`: all pass, test user deleted (204).
- Sourabh approved one more live URL for the warm "Open here" timing. Wikipedia "Forward guidance"
  (dry run: new): open 6.64 s, article 7.54 s, notes 43.7 s, no reload — same as the first live
  run, so it isn't instance cold start; phase 1 itself is slow on Cloud Run (local 0.84 s).
  Added `fetch_ms`/`extract_ms` to phase 1 logs (M7). M9 item: preload the ingestion imports at
  startup during judging (min instances 1). contents/ now 312; ops/ingest anonymous 3.
- milestone-reviewer round 1: **FIX** (4 blocking, 2 should-fix, 5 follow-ups). Applied so far:
  onboarding status refetched after the welcome flow (no stuck "Opening…"); map refreshes after
  Apply/Undo/Reset; consent screen has Export and Delete (with Escape/focus) and accurate wording;
  44 px preview summary and header targets; delete confirmation focus + Escape; settings errors
  shown; edit history labels; summary/bars agree (rounded θ, unrated domains not named, bars say
  "not rated yet"); reset restores session settings; liked ids pattern; expired edits cleaned on
  parse; gate logic vitest; live check asserts + announced counter write. Evidence re-run on the
  final code saved to docs/evidence/M7-harness.txt (onboarding → library without reload via last
  answer and Skip; spans 8 vs 2 and 9 vs 5; software vs cricket analogies; axe 0 ×4; no overflow;
  31/31 Tab stops; node card focus return; map renders and refreshes; preview leaves settings
  unchanged; explanation 56 → 23 words — a cache hit in this re-run because the earlier run had
  cached the same short Background; the earlier run's miss is in the harness log).
- Still to do before re-review: STATUS §15 numbers from the evidence file, STATUS deviations
  (trend table only, live check shape) and decision row order, harness headroom wording
  ($0.18, not $1), re-run milestone-reviewer.
- Orphan cleanup: Sourabh approved deleting the 8 docs of his 12:28 IST session. Dry run (read-only)
  found **21** docs under that uid (users doc, 18 events, weekly/2026-W41, demo_graphs/newcomer): his
  tab kept posting events to the local dev server (production Firestore) until it was stopped for
  the M6 deploy. **Nothing deleted**; asked Sourabh to confirm 21. The one-off script lives outside
  the repo.
- milestone-reviewer round 2: **SHIP**. Follow-ups noted: re-measure the 44 px header next run;
  PR mentions the phase-1 timing logs (e1f51dc) as an out-of-scope change.

### Ship
- PR #16 squash-merged (e7f06f0), CI green, milestone-reviewer SHIP. Deployed API
  `readlayer-api-00012-ccv`, then web `index-Dm3tU99c.js` (Sourabh approved).
- Orphan cleanup: Sourabh approved 21 docs; deleted 21 (count-guarded), nothing left under that uid.
- Live: live_check_m7 all pass; browser pass clean (axe 0 ×3, console 0, 44 px header confirmed);
  demo annotations identical before/after; 1 pre-M7 Google user doc now gated at consent.
- Pending: Sourabh's live Google check.

---

## Scope change (Sourabh, 2026-10-10)
- M2.2 is **full scope** (decision 32): online growth, jurisdiction in link_confirm, strictness,
  Russell mislink, 30-article held-out set, ≥ 75% linked. BUILD_PLAN gets a full M2.2 section
  (out of M9 and the post-hackathon list); STATUS milestone rows, deviations and next actions
  updated.
