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

## Scope change 2 (Sourabh, 2026-10-10, decision 33)
- Not a business-only reader. New order: M2.2 (full scope + open domains) → new M7.5 ("For you"
  feed, "Read any link", reading goals) → M8-local → M9. Demo personas unchanged.
- M8 paused on branch `m8` (local commit 2f037a1: redaction format and false positives,
  NOT_CORPUS exclusions; 512 tests pass). Plan stays approved; resumes after M7.5.
- Taxonomy chosen (14 domains, old four ids kept so existing data stays valid): economics,
  finance, business, policy, politics, law, technology, science, health, environment, sports,
  culture, education, society.
- Freeze check: tight but not yet judged at risk (M6 rest and M7 each took a few hours). Real
  risks are non-coding: seeding non-business concepts needs production writes beyond current
  counts, and each deploy waits on Sourabh. Re-checked after the M2.2 plan is sized.
- DESIGN feed and goals sections are written with the M7.5 plan, so plan-reviewer sees them.
- Asked how the 75% applies with non-business articles. Sourabh (decision 34): headline is the
  frozen-graph rate (business ≥ 75%, non-business aim 60%, < 50% → stop and tell him); after-growth
  rate reported as production behaviour; grown-concept precision ≥ 90% on a judged sample. Seed new
  domains from Wikipedia glossaries via safe_fetch + deterministic parsing; show counts and writes
  before writing.

## M2.2 (full scope + open domains, decisions 32–34)

### Plan
- docs/plans/M2.2.md. Glossary sources probed live through safe_fetch (entry counts in §B.1);
  society has no parsable glossary, so it keeps 0 seeds and Sourabh decides.
- plan-reviewer: REVISE ×4 (11, 8, 10, 2 items, all applied), then **APPROVE** in round 5 (2
  nits applied). Key changes: no explain/restate/verify bumps (warm demo caches stay valid);
  API deploy before the seeded graph; growth only for Google readers with phase-1 slots and a
  `growth_counts` subcollection; `GROWTH_ENABLED` in deploy.env.yaml, default false; frozen
  held-out demand set committed before any model run; held-out report committed under evals/;
  Concept.kind stored; Chancellor of the Exchequer and FTSE Russell added by override.
- Checkpoint: end of day Oct 11 IST, unfinished parts go to Sourabh as a cut question.
- Sourabh (decision 35): growth applies to demo readers too, within the existing caps; persona
  graphs untouched. Plan §C.1 amended (reverses round-1 item 6), live check now runs as an
  anonymous demo reader pasting a link (no operator script). Amendment sent to plan-reviewer.
- plan-reviewer on the decision-35 amendment: **APPROVE**; its 5 nits applied (cleanup via
  DELETE /v1/me, pre-flight cap check, evidence before cleanup, complete write list, fold review
  list to Sourabh).

### Build (in progress, paused at usage limit, 2026-10-10)
- Done and committed: 14-domain taxonomy (API, web, calibration gate); overrides remove_alias /
  add / never_merge_kind (Russell, Tax alias, Chancellor of the Exchequer, FTSE Russell);
  concept_define v3; extract_demands v2; frozen eval inputs (link_confirm 16 cases,
  link_variants 150, link_merge 100, held-out list to 30 with domains, frozen demand set for the
  new 15 with sha256); linker eval suite; held-out headline script; jurisdiction module + tests.
- Before (linker suite, v2): link_confirm 13/16 (fails: levy, preferential, Russell Indexes),
  variant precision 83% (1 of 15 batches answered by the fallback model after a 45 s timeout,
  both runs logged), merge agreement 71/100. Old-15 extract counts v1 186 → v2 169
  (evals/results/heldout_extract_counts_v1_v2.md).
- Before headline (held-out, frozen graph) was running in the background at the pause; check
  evals/heldout_report.md, and rerun `uv run python -m scripts.heldout_headline --label before`
  if it has no "before" block.
- Next: link_confirm v3 prompt + rendering of site/kind/jurisdiction and the code filter in
  plan_links; kind/jurisdiction backfill; glossary parser and seeding dry run; then the counts
  message to Sourabh (plan run order step 6).
- Before headline (held-out, M2.1 graph, link_confirm-v2): business 61%, non-business 11%
  (n per domain 5–31; sports 5 and culture 6 are very small for a per-domain stop rule).
- Linker v3 (code jurisdiction filter on stored kind + link_confirm-v3) and link_merge-v2,
  concept_prereqs-v2: suite 13/16 → 14/16 (levy fixed; preferential still null; Russell
  Indexes → null, defensible since the phrase means the indices; in production it links by the
  new FTSE Russell alias), variant precision 83% → 86%, merge agreement 71 → 72, 0 fallbacks.
- profile_edit: "before" is the shipped M7 run (profile-edit-v3, 6/6, 4/4), since the code
  already sends 14 domains. v4 broke P06 (5/6: the fan line dropped the cricket frame); v5 fixes
  it with a football example (6/6, 4/4). Both runs kept in evals/report.md.
- Seeding dry run, first attempt stopped: dedupe compared every candidate pair ≥ 0.88 (~12,000
  link_merge pairs, 619 calls, $0.74 before I stopped it; projection had guessed 39 calls). Fixed:
  each candidate is compared with its nearest graph concept and at most its 3 nearest
  candidates (the build's top-k rule), and --project now counts the real pairs (7,686,
  projected $1.71). Deviations from the plan, both logged: kind for pre-M2.2 concepts comes from
  concept_jurisdiction for all of them (the build cache keys can't be mapped back to concepts);
  exact matches of existing concepts are dropped rather than adding their aliases.
- **STOP (decision 34 stop rule), 2026-10-10 ~19:15 IST.** Local frozen-graph headline on the
  seeded graph (5,201 concepts, link_confirm-v3): business 64% (target 75%), non-business 13%
  (aim 60%, floor 50%; every non-business domain under 50%). Before: 61% / 11%. After growth
  (production behaviour): business 89%, non-business 69%, all 80%. Grown-concept precision
  26/30 = 87% (target 90%). Nothing written to production; seeding upload, re-link and
  held-out storage NOT done. Asked Sourabh how to proceed.
- Sourabh (decision 36): go with the recommendation. Next: tighten growth to ≥ 90% precision,
  then show the exact production writes with the deploy request, ship, then M7.5.
- Growth tightened: link_confirm check on each new concept + concept_define v4 scopes. Rerun
  (seeded-growth-v2): after growth business 89%, non-business 66%, all 78%; grown precision
  29/30 = 97% (not independent of the first sample; disclosed in the report).
- Open domains on the harness (seeded graph): 14 interest chips, axe 0 and no h-scroll at 1440/390
  light/dark; Health+Sports reader's calibration filled health (16) and sports (8) concepts;
  profile leads with Health/Sports, 12 others folded; map lists all 14.
- Found and fixed a live bug from M7: the Delete my data label was invisible (account.css filled
  .btn--danger + profile.css outlined rule = danger text on danger background), both themes.
- milestone-reviewer round 1: FIX (9 items: STATUS accuracy, deviations, open decisions, missing
  tests, startup guard); all applied. Round 2: **SHIP**; follow-ups applied (cost line, injection
  test renders the real prompt against a forged delimiter).
- Harness fix: the emulator budget refused every call once production spend passed $1 (cap now
  copied spend + allowance). Growth timing on the harness (growth on, seeded graph): technology
  article 4 concepts in 20.0 s, health 3 in 6.9 s; growth timeout raised to 30 s (deviation logged).

### Ship
- PR #18 squash-merged (a627081), CI green, milestone-reviewer SHIP. Sourabh approved the whole
  post-merge sequence. API 00013 (old graph) → seeded upload (backup M2.1 file) → 00014 (seeded,
  load 1.08 s) → re-link 42 corpus docs → 15 held-out docs stored (store_heldout, cache only) →
  7 held-out docs re-linked → GROWTH_ENABLED true (bc4f55a, CI green) → 00015 → live growth check
  passed (5 concepts, environment) → fold (backup seeded file) → 00016 loads 2026-10-10-folded-5206
  → web deployed (index-oV20XPLM.js; Delete fix live in ProfilePage/WelcomePage CSS).
- Issues seen live: same-article duplicates (Forever chemicals / PFAS), PFOS → PHOSITA prerequisite.

## M7.5 ("For you" feed, "Read any link", reading goals; decisions 33, 37, 38)

### Plan
- Sourabh: generalise the explanation prompts in M7.5 and keep society (decision 37); demo
  personas get a predefined, pre-seeded feed with a subtle "prepared in advance, may be dated,
  sign in for a live feed" note (decision 38).
- plan-reviewer round 1: REVISE (16 items, applied; item 12 replaced by decision 38's pre-seeded
  demo feed). Round 2: REVISE (2 items + 7 nits, applied): per-request visibility filter after the
  shared caches (two judges on one persona template never see each other's pasted pages), and
  one shared `NOT_CORPUS` constant.
- **Note for resuming M8:** M8's approved plan hides NOT_CORPUS docs from everyone; M7.5 makes them
  visible to the reader who brought them in (users/{uid}/ingested). Update the M8 plan to keep that
  rule before building on the m8 branch.
- plan-reviewer round 3: **APPROVE**; its 6 nits applied (filter before the per-relation cut,
  ingested on the pending branch and on submitted text, known_urls from the filtered set, exact
  count before deploy, one ingested read per request).

### Build
- Sourabh (decision 39): a dedicated **Design pass** milestone right after M7.5 is merged and
  deployed, before M8 (Medium-style tokens and type, library as a feed, reader, profile and
  knowledge map). BUILD_PLAN and STATUS updated. M7.5's web parts stay functional and accessible,
  not polished, to avoid doing them twice. Freeze watch: M7.5 by Oct 12, design pass Oct 13, M8
  Oct 14, M9 Oct 15; the Oct 12 checkpoint stays.
- warm_demo `--dry-run` and `scripts/live_check_m7_5.py` (demo snapshot, goals 403, Read any
  link privacy across two demo readers). DESIGN §17 (For you) and §18 (goals), route rows,
  §11.4/§11.5; STATUS deviations (private pasted pages: **7** production `user_ingested` docs,
  0 `extension`, read-only count), caps, Tavily projection.
- Harness snapshot check found the feed unfit to show: "latest news" returned section/tag pages
  (8 of 9 articles failed the 400-word check), "Technology explained" returned kids' lessons
  and Shorts, podcasts came back as chart pages. Probed providers (≈ 30 Tavily credits, ≈ 6
  YouTube searches, harness only) and fixed deterministically: article phrase "news this week",
  article-shaped URL check, show pages only for podcasts ("podcast"), YouTube 4–20 min from the
  last 30 days ("news explained"), relevance by label / short stem / taxonomy scope words, and no
  `exclude_domains` on feed news (with it Tavily returned 0 articles of 9). Newcomer snapshot now
  4 technology + 2 economics readable articles, news-explainer videos, real shows. Queries are
  still only a taxonomy label + fixed phrase (decision 33).
- Sourabh (decision 40, mid-run): Design pass additions — Gloss name, `docs/design/mockup.html`
  as the visual target, Margo mascot, reader details, mobile. His BUILD_PLAN edit and the mockup
  are committed with this docs commit; STATUS decision 40 logged. M7.5 continues first.
- Harness acceptance (restarted harness after the session restart; scratch helpers recovered
  from the transcript). Fixed on the way: feed topics from chosen interests only (≥ 0.5),
  English-only titles, empty day entries retried after an hour, rec signals batched in the
  client (per-card requests contended on one Firestore doc and stalled page loads to 31 s),
  learning-goal progress note, intro spacing, sign-in copy, failed thumbnails. All checks pass
  except the live-only items; goal boost covered by tests only (no matching live item). STATUS
  §17, `docs/evidence/M7.5-harness.txt`. Next: milestone-reviewer.
- milestone-reviewer round 1: **FIX** (7 items: Not interested did nothing, unbounded empty
  retries, missing yesterday fallback and unrecorded seeding deviations, an unsupported evidence
  number, missing tests, stale STATUS, two notes). All fixed; round 2: **SHIP**.
- PR #20 opened, CI green, squash-merged. Deployed API (revision 00017) then web, each with
  Sourabh's yes. `seed_demo_feed` dry run then real (24 search calls; three topics thin on
  articles, recorded in §5 for the Oct 16 re-seed). Tavily: Researcher plan, 398/1,000 credits.
  `warm_demo` 24/24 verified, pass 2 all cache hits. `live_check_m7_5` passed on a re-run: the
  first run stopped at its 5 s assertion (6.8 s, first ingest on the new revision, known cold
  imports). Live axe clean. A browser test reader was first "deleted" against the Hosting origin
  (SPA 200); caught and deleted through the API (204). Left: Sourabh's Google check.

## Design pass (decisions 39, 40) — started 2026-10-11

- Sourabh: M7.5 live Google check done (feed, Read any link, goals); start the Design pass.
- Plan `docs/plans/design-pass.md`: stages 1–5 over Oct 11–13, checkpoints end of Oct 12 and
  midday Oct 13 (ask before cutting). Before screenshots from the live site first
  (`docs/evidence/design/before/`). Reusable headless-Chrome helper now lives in `tools/shots/`
  (scratch helpers were lost twice on session restarts).
- plan-reviewer round 1: REVISE (16: band source, refresher rarity, pre-read path, four required
  items I had dropped — action-bar Helpful, interest on domain cards, the tagline, Margo in
  empty/error states — persona chip, map node data, Save on feed rows, annotator opt-in safety,
  m8 conflicts, map keyboard and contrast, bundle, recap correctness, shift warm-up, before
  shots, second checkpoint, DESIGN sections). Round 2: REVISE (map solid vs ready wording;
  extension pre-read must skip known steps). Round 3: **APPROVE**; two nits applied.
- Build (Oct 11): API A1–A7 with tests (span band/level from the uncapped concept band; ticked
  pre-read step; Say it simpler / Go deeper through the verified path; recap bands; all-topics
  map overview; Saved; article Helpful), `warm_demo --shifts`. Refresher-share measurement first:
  8–16% of shown spans, both styles on a demo article, so no question for Sourabh. Web stages 1–5:
  tokens and fonts (measured fallbacks), Margo, Gloss name, top bar, library as a feed (For you ·
  Topics · Saved, rows, sidebar), reader (action bar, path, highlight levels, margin notes with
  Margo, card pitch and depth buttons, recap), profile (domain cards, SVG map with inspector,
  Cytoscape removed), sign-in and welcome. The annotator's sidenote and sheet already existed, so
  the card changes stayed in card.ts (deviation recorded). Found and fixed on the way: a 32px
  sideways scroll on phones (top bar), sub-44px density and Up next buttons, the persona chip's
  missing name in compact mode, a heard-of dot under 3:1, domain cards counting the whole graph.
  Both checkpoints met on Oct 11. Next: milestone-reviewer.
- milestone-reviewer round 1: **FIX** (6): the lockfile and wordmark script uncommitted (CI would
  fail), the recap listing a "Not really" concept twice, Margo blinking during reading,
  `warm_demo --shifts` running into the anonymous cap silently, missing planned tests and the
  recap's neutral fallback, stale STATUS lines. All fixed: one row per concept ("Next on your
  path"), Up next's top two under "Read next" when nothing teaches the unknown concepts, blink only
  before the reader scrolls into the article, `capped` on the explain response, one demo reader
  per article in `warm_demo` with capped cards reported and a non-zero exit, tests for the shift
  cap and fallback, bands, the saved cap, Margo `aria-hidden` and tab ↔ URL. Also from the review:
  44px card buttons, no overlap between depth buttons, "Back to my level" after a rejected shift,
  Helpful keeping focus, a one-row phone action bar, a light `GET /v1/me/saved/ids` for the reader,
  snippet cleanup (markdown, sponsor links), domain-card copy matching what it counts.
- After screenshots (32): `docs/evidence/design/after/` (library For you / Topics / Saved,
  reader, open card, phone sheet, recap, profile, map inspector, sign-in); before (20):
  `docs/evidence/design/before/`; audits: `docs/evidence/design/after-audit.txt`; flows,
  contrast and measurements: `docs/evidence/design/acceptance.txt`.
- milestone-reviewer round 3: **SHIP**. PR #22, CI green, squash-merged. API deployed (revision
  00018, Sourabh's yes); web deployed (Sourabh: "deploy on web without permission"). Stopped the
  local harness and a stray wait loop (Sourabh asked to close unneeded background tasks).
- Live check: names, axe, highlight levels, Say it simpler and Helpful pass; Save failed because
  CORS didn't allow PUT (local dev proxies /v1, so no harness run could catch it). Fix on branch
  `design-cors`: PUT allowed, plus a test that checks every method in the OpenAPI schema against
  the CORS list (first version passed vacuously because FastAPI wraps included routers; rewritten
  and shown to fail without the fix).
- #23 merged on green CI, API redeployed (revision 00019, Sourabh's yes). Live re-check: Save works (preflight allows PUT; saved article in the Saved tab). Design pass done. Next: M8-local, starting with the m8 rebase.

## Landing and onboarding (decision 41) — started 2026-10-11

- Sourabh (decision 41): a Landing and onboarding milestone after the Design pass, before M8.
  Recorded in BUILD_PLAN and STATUS. Before screenshots of the current live sign-in landing:
  `docs/evidence/landing/before/`.
- Plan `docs/plans/landing-onboarding.md`. plan-reviewer round 1: REVISE (21: static-hero flash on
  other routes, hint key, fonts and the no-network definition, the 60 KB budget meaning, Lighthouse
  install, free-text tests, consent order, discover cost abuse, pick trusting the client, know rules,
  onboarding step, the demo build script's cache precheck, an inaccurate trust line, persona names,
  dead card buttons, routing gaps, acceptance gaps, the extension line, the eval parser, " and "
  splitting, docs and deploy). Round 2: **APPROVE**; nits applied.
- Open question to Sourabh: none of "F1", "startups", "Indian politics", "Formula One" resolve on the
  live graph (checked live, $0.002); proposed taxonomy-topic fallback. The resolve response reserves
  `topics: []`; work proceeds on everything else.
- Sourabh answered (decision 42): topic fallback approved (alias list, then phrase-only embedding
  above a threshold from labelled phrases, shown back as "F1 → Sports" and changeable, consent line
  updated). Also approved warming the 5 landing-demo notes: `build_landing_demo.py --paragraph
  23324188:p5 --warm` → 5 cached, verified cards in `apps/web/src/landing/demo.json` (production
  spend $0.0778 → $0.1081; both temporary readers deleted). Commit 8140d44.
- Decision 43 (Sourabh): stop with "READY FOR /clear" at milestone ends and at committed
  mid-milestone checkpoints. Added to CLAUDE.md and STATUS §10.
- Build step 1 done: annotator `actions: "demo"` + `demoAction` (one call to action replaces Knew
  this / Helpful / This is wrong; records nothing), `ANNOTATOR_VERSION` 0.6.0, 2 vitests (43 pass);
  web `readlayer:signed-in` hint written in `auth.ts` on every auth change (`SIGNED_IN_HINT`).
  Typecheck and web tests green.

- Build steps 1–4 of the old list done (765726d): static hero in index.html generated from
  `HeroStatic` (vitest pins them; `UPDATE_HERO=1` rewrites), boot switch in theme-init.js, landing
  sections, live mini-demo (0 fetch/XHR after load), privacy page, eval-numbers generator, routing
  and deep-link return, SignInPage deleted. Annotator 0.6.1: a kept mark takes the new reader's
  level (found on the landing: the cricket fan's "bps" stayed "new").
- **Decision 44** (Sourabh: visuals; light default; repo public at submission after gitleaks, in
  M9) and **decision 45** (wider layouts: landing now, feed/profile/reader as a "Wide layout"
  follow-up before M8). Plan amendment V1–V9: plan-reviewer REVISE (9 items applied: spend gated
  on Sourabh's yes with ≤ 8 images / $0.60, per-image price when LiteLLM can't price, the
  generate_image contract and tests, reference rasterising, headroom check, media dry run, WCAG
  2.2.2 pause control, build order), then APPROVE; V9 APPROVE (nits applied).
- Done: light default (7b00cf0); V1 hero Margo with persona moods, V5 bands and teal trust band
  (3aff446); annotator 0.6.2 (a scrolling card body is a focusable region, from axe
  scrollable-region-focusable on the landing); V9 layout (dfed2a1); V2 product shot and V4 clips
  (05222db) by `tools/shots/landing_media.py` on the live site as temporary demo readers: 6 runs
  in all, each reader deleted (DELETE /v1/me 204); reruns fixed a blank desktop shot, crops, a
  flaky map wait and ffmpeg timing. One "Say it simpler" generation (cricket fan, "tighter
  policy", ≈ $0.005): the Newcomer's "bps" is already at the lowest band. Clips 3.5–5 s, 37–91 KB.
- Checks (local preview, `tools/shots/landing.py`): axe 0 at every impact on "/" and /privacy at
  1920/1440/1280/390, light and dark, card open included; no horizontal scroll; first view at
  390×844 = 316 KB; landing chunk 6.9 KB gzip, main 145.1 KB.
- V3 code ready, not run (05ed5d7): `llm.generate_image` (route `landing_art`, no fallback,
  header-checked PNG/JPEG ≥ 512 px, per-image price fallback), prompt `landing-art-v1`,
  `scripts/landing_art.py` with its own cap; 11 offline tests. Dry run: MODEL_IMAGE
  `vertex_ai/gemini-3.1-flash-image`, 6 calls, ≈ $0.40, hard stop 8 images / $0.60; production
  spend today $0.11 of $8.
- Sourabh (2026-10-11, after the /clear): **yes** to the illustrations: Gemini 3.1 Flash Image,
  six images, hard stop at $0.60; pick the best three; log model, prompts and cost.

- V3 done: `landing_art --confirmed` made 4 images, then Vertex 429 crashed the script (the
  uncaught `LLMUnavailable`); fixed: a quota/outage error now stops the run cleanly, and
  `--scene <name>` finishes one scene (test added). `--scene shredder` made 1 more, then 429 again
  (clean stop). Total **5 images, $0.339**, ledger $0.1113 → $0.4506 (429s unbilled). Sixth not
  retried: each scene had a usable pick. Picks: jargon v1, tabs v2, shredder v1 (jargon v2 drew
  Margo as a human, off-model). White → transparent, 5:4, WebP 460/920 px
  (`apps/web/public/landing/problem-*.webp`), `ProblemArt` `<img>` with alt text replaces the SVG
  line glyphs (`Illustrations.tsx` deleted), dark = invert + hue-rotate, footer credit. Checks on
  the local preview: axe 0 and no horizontal scroll at 1920/1440/1280/390, light and dark; teal
  6.3:1 (light) and 8.0:1 (dark) on the wash; first view at 390 = 211 KB. Model, prompt, cost in
  DESIGN §20.1 and STATUS §7; crops and candidates in `docs/evidence/landing/illustrations/`.

### Next steps (resume here, in order)
1. Lighthouse on the local preview (`pnpm --filter web build && pnpm --filter web preview`),
   persona chip labels ("Newcomer (software engineer)" …), before/after screenshots into
   `docs/evidence/landing/`.
2. Checkpoint 1 (end of Oct 12 IST), then the onboarding API (§C incl. decision 42) and the
   2-screen WelcomePage (§B).

- Resumed after /clear (2026-10-11). Dark illustrations re-verified on a fresh build: the invert
  filter gives white strokes and lighter teal on the dark wash at 390 and 1440, clearly visible;
  no backing needed (shots in `docs/evidence/landing/illustrations/`). Landing checks on the
  fresh build: axe 0 and no horizontal scroll everywhere, first view at 390 = 211 KB.
- **Decision 46** (Sourabh, landing polish, 9 items: payoff-first hero with an open note, Margo on
  the note, fuller nav and a higher hero, phone-only product shot on the hero card, sentence-case
  labels, halved section padding, problem row + pull quote, re-cropped clips, no empty halves).
  Recorded in STATUS §10. Before shots: `docs/evidence/landing/d46-before/`. Plan amendment P1–P6
  drafted. plan-reviewer round 1: REVISE (10: whole demo inside 1440×900, a 390 fallback order,
  small-caps and tracking too, inline card semantics, persona-switch race, one-frame static→live
  swap, phone geometry, measured clip legibility, removals together, slip plan); plus 2 found in
  the annotator (no focus trap, no hover peeks inline). Round 2: **APPROVE**; nits applied (12 px
  phone clip figure in STATUS; if the phone only fits from 1280, it gets logged and noted in the
  decision 46 row). Lighthouse moves after the polish.
- P1 + P2 built (time logged per round 1 item 10): annotator 0.7.0 `inline` host (group role,
  revealed when the explanation settles, `onCardReady`, quiet host opens, no hover peeks, no
  close on outside/scroll/Escape, no focus trap, open() doesn't scroll; 7 vitests, 52 pass) and a
  fix found on the way: the demo button's dark pill was overridden by the generic `.rl-btn` rule
  (now `.rl-btn.rl-btn--demo`). Hero: featured note open on load (`FEATURED_NOTE`), static
  `DemoNoteStatic` in a fixed-height slot (330→390 px desktop, 280 px phone), Margo on the note's
  top edge, "Read as:", nav (How it works, Privacy, Sign in, Try the demo). 1440×900: whole demo
  ends at y 858. 390×844: fallbacks (a) fine print below the demo, (b) CTAs on one row, (c) level
  line hidden were all needed; note title + 2 Background lines in view. Main 146.2 KB gzip.
  Next: P3 phone shot, P4 sections, P5 clips, then the P6 checks in `tools/shots/landing.py`.
- P3–P5 built: phone on the hero card (desktop only, rendered only ≥ 1024; desktop shot files and
  capture removed; no V6 file-size vitest existed, the size budget lives in landing_media.py),
  problem head row + pull quote, centred formats, final CTA with the map clip, `#how-it-works`.
  Clips re-recorded on the live site in 2 runs (the plan's cap): 1024×900 at DPR 2, crops tight to
  term + card (cut under the Background), posters checked non-blank; each run 1 temporary reader,
  `DELETE /v1/me` 204 both times; 0 generations (precheck: all cached). Clips keep their own shape
  in a staggered 2-column grid (the old shared 3:2 frame letterboxed them).
- P6 checks (`tools/shots/landing_d46.py`, run by landing.py) first run: all pass except axe
  scrollable-region-focusable on the hero card at ≥ 1280 and clip-map at 390 (10.4 px < 12).
  1440×900 demo bottom 879; 390×844 note + Background line by y 820; swap spread 0 px; no caps.
- **Decision 46b** (Sourabh): left column top-aligned and filled (three value lines with tiny
  Margo faces, a proof line from evals.json), the open note shows "What the author is saying" in
  full, check 1440×900 / 1280×800 / 390×844, then freeze the landing and go to onboarding.
  Amendment Q1–Q4 drafted (real numbers: 24/25 good, not Sourabh's example 25/25); plan-reviewer
  running.
- 46b plan-reviewer: round 1 REVISE (3: value lines after the demo below 1024, what must pass at
  1280×800, clip-map crop guarded by a frame diff), round 2 **APPROVE** (nit: a second proof line
  after the demo below 1024 for focus order, applied). Built: annotator 0.7.1 (overflow re-check on
  inline reveal, vitest; 53 pass), top-aligned copy column with Sourabh's three value lines (Margo
  faces) and the proof line from evals.json ("15/15 … · 24/25 …", the data, not the example's
  25/25) linking to `#how-we-test`, note at natural height ("What the author is saying" in full,
  no inner scroll, all personas, 1440/1280/390), source line into the caption, 19px demo
  paragraph. 1440×900: whole demo in view (bottom 864 for the cricket fan); copy vs card 75px.
  1280×800: copy vs card 137px (reported). clip-map re-crop not possible: the frame diff shows the
  map re-lays out across the full width, so the crop stays 480 (390: 10.4px, reported).
  New failures from the natural-height note: Margo touching the paragraph at 1440, swap spread.
- **Decisions 46c/46d** (Sourabh): hero without the phone, source line in the card header, "Read
  with Gloss:" chips, ±40px column/card alignment with the whole hero in view at 1440×900 and
  1280×800; clips as equal 16:10 tiles at natural zoom (whole lines, never upscaled), each showing
  its step, mid-clip posters; then freeze and go to onboarding. Amendment R1–R3 drafted;
  plan-reviewer running.
- Sourabh (46d answer): "don't cut around the reload. Fix it in the product … Add a test. Then
  record clip 1 as one continuous take. Everything else in your 46c/46d plan is approved, including
  leaving out the second phone frame." Plan rounds: product fix REVISE ×2 (second chip / chip kept,
  refresh=1 not a page view, scorer test; deploy order), then APPROVE.
- **PR #25** (Know-this refresh, branch off main): milestone-reviewer FIX (recap snapshot reset by
  the refresh; STATUS) → FIX (recap snapshot from the previous view's notes after a switch; fixed by
  tagging notes with their view) → **SHIP**; CI green; squash-merged (97ee1bd). API deployed
  (revision 00020) and web deployed, each on Sourabh's yes. Live check: a temporary demo reader
  answered "Not really" on "hedging": inked in as a new-idea mark, one chip "Noted, thanks.", no
  reload; reader deleted (204). main merged into `landing` (4c2035c; landing's earlier drafts of the
  fix files replaced by the reviewed ones).
- 46c built (hero: phone out, source line in the card header, Read with Gloss chips; 1440×900 copy
  vs card 3 px, 1280×800 32 px with the level line hidden at heights ≤ 820, whole hero in view).
- **Decision 46e** (Sourabh): device frames with HD full-UI captures (a "See it in action" section
  after the hero: monitor with the feed, laptop with the reader; phone on mobile), How it works as
  framed full-window loops with a gentle zoom toward the action (≤ 1.15×), section padding ~128 /
  ~72 px, loops ≤ 600 KB, posters ≤ 120 KB. His answer on the 11px question: "not relevant any
  more; on phones the framed full-UI shots are pictures of the product, that's fine. Keep a 'tap to
  play' with the poster on phones if autoplay is blocked." Amendment S1–S5 drafted; plan-reviewer
  running.
- 46e plan-reviewer: round 1 REVISE (4: feed capture must cost nothing, final CTA in the same frame,
  pause stops the zoom, media checks' viewports + slip rule), round 2 **APPROVE** (nit applied: 1x
  loops for < 1024 via `<source media>`, small first). Precheck extended: the Newcomer feed is the
  seeded `persona_feeds/newcomer` snapshot (31 items, anonymous feeds never search) and every
  Up-next query for the demo personas is a fresh cache hit (0 searches), refusing otherwise.
- 46e media from the live site, 3 runs (the plan's cap), each 1 temporary reader deleted (204):
  run 1 stills OK (2880×1800 / 780×1688 captures; 1x ≤ 107 KB, 2x ≤ 245 KB) but loop frames were
  1440 wide and clip 2 found no note in the first view; run 2 frames still 1440 (screencast
  ignores emulated DPR) and clip 2's notes arrived with the text; run 3 with Chrome launched at
  device scale 2 and 700 ms emulated latency for clip 2's take: all four loops native 2880×1800
  (≤ 546 KB; 1x ≤ 242 KB; posters ≤ 102 KB), clip 2 starts plain (0 → 12 marks). 0 generations,
  0 searches. Found and fixed: annotator 0.7.3 (an inline card's first reveal grew from a
  skeleton height, an 88/172 px jump at the swap; test fails without the fix); stills render only
  when near (Chrome's lazy margin fetched the phone still in the 390 first view).
- Checks (local build): all decision 46 checks pass; axe 0 at 1920/1440/1280/390 light and dark;
  first view at 390 = 175 KB, no landing media before scroll; swap ≤ 1.3 px. Lighthouse 12.8.2:
  desktop perf 99, a11y 100, LCP 0.9 s, CLS 0; **mobile perf 81, a11y 100, CLS 0.048, LCP 4.9 s
  (gate 2.5 s fails)**: observed LCP 212 ms (the demo paragraph once the serif web font lands);
  the simulated figure follows the font and script downloads. Experiments (reverted): fonts
  without the opsz axis (−150 KB) → 4.6 s; `display=optional` → 1.8 s, perf 98, CLS 0. Asked
  Sourabh (optional fonts app-wide vs keep vs self-hosted subsets).
- Sourabh (screenshot): no gap under the nav and a high empty band at the bottom on a tall window.
  The desktop hero now fills the first view (`min-height: 100svh − bar`) and centres its content;
  1440×900: 71 px under the bar, whole hero in view; 1280×800 still fits (card bottom 797);
  1600×1100: equal room above and below. All checks re-run green.
- **Decision 47** (Sourabh: self-hosted trimmed fonts). plan-reviewer round 1 REVISE (stop rule,
  the ₹ sign, stale Google references and silent bad paths), round 2 APPROVE. Built:
  `tools/fonts/trim_fonts.py` (Fontsource variable 5.3.0 / 5.3.1 via `npm pack`, Latin `wght`
  files trimmed with fontTools to 400–800 / 400–600 / italic 400–500: 44.7 + 33.4 + 32.3 KB,
  ≈ 300 KB before) plus a one-glyph ₹ file per face (0.9–1.1 KB, own `unicode-range`), versioned
  names, `/fonts/**` cached immutable in firebase.json; fonts.css `@font-face` (swap), the hero
  headline and body files preloaded, Google Fonts links gone; fallback metrics re-measured
  (the old serif numbers came from Google's opsz display cut at 100px). Font checks in
  `landing_d46.py`: preloads return `font/woff2`, every face loads, ₹ is a real glyph.
- Mobile LCP then: 5.9 s (observed 620 ms) with fonts at 8 ms, so not the fonts. Cause 1: React
  replaced the static hero → `hydrateRoot` on the landing boot (`main.tsx`; index.html now from
  `renderToString` so text nodes match; `useSyncExternalStore` hooks get a server snapshot);
  desktop LCP 0.5 s, perf 100. Cause 2 (remaining): the landing chunk re-mounts the hero and the
  new paragraph (slightly larger once highlights are drawn) is a new LCP candidate at ≈ 640 ms
  (trace: candidate 1 at 40 ms, 69,300 px²; candidate 2 at 644 ms, 70,980 px²; an out-of-flow
  dot only shrank the growth to 210 px²). Sourabh: accept the mobile miss for now; the mount
  restructure goes to the M9 / tweak-window list (STATUS §5).
- Sourabh: a short transition between light and dark: the toggle cross-fades the page with View
  Transitions (280 ms; instant under reduced motion or without support).
- **Landing frozen** (Sourabh, 2026-10-11) until the tweak window.
- Final landing checks (local build, frozen state): all decision 46 checks green (390×844 first
  view needed the phone demo paragraph at 18px: the self-hosted serif sets a little wider), font
  checks green, axe 0 everywhere, first view at 390 = 286 KB (fonts now first-party), no landing
  media before scroll. Unit tests: web 45, annotator 54.

### Next steps (resume here, in order)
1. Onboarding (decision 41 parts B and C, with decision 42's topic fallback), as planned in
   `docs/plans/landing-onboarding.md` §B, §C and "Decision 42": the API first
   (`POST /v1/onboarding/resolve` with the alias list and the embedding fallback, its labelled
   set `apps/api/evals/cases/onboarding_topics.yaml` committed before choosing the threshold),
   then the 2-screen `WelcomePage`. Landing is frozen (tweak window only).
2. Then acceptance, milestone-reviewer, PR from `landing`, deploys (Sourabh's yes), live check.
