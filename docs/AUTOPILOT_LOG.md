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

- **Onboarding API built** (b0f8827, labelled set committed first in 14b7a54). Routes in
  `app/me/onboarding_flow.py`: resolve, discover, pick, know, finish; consent-v2; step
  `discover`; `post_onboarding` re-applies screen-2 picks (Edit → Continue) and returns
  `next: "discover"`. `FeedSearch.gather_specs` (topic and `feed:c:<id>` concept keys share
  de-duplication, limits, backoff, yesterday fallback; `may_start` reserves the reader's discover
  count only when a new search would start); concept searches have a shared daily sub-cap
  (`onboarding_concept` counter in ops/search, 20). 22 new tests (privacy: no search during
  resolve, models see only individual redacted pieces, nothing of the text in logs at DEBUG or in
  the store; mutation-checked: a planted debug log of the text fails the test); 662 pass.
- Topic threshold (decision 42): `evals/onboarding_topics.py` on the 27 committed phrases, one
  embed call ($0.00003, counted in the production spend counter like earlier evals). Similarities
  are bunched (0.80–0.92; "asdf qwerty" 0.855), so the lowest threshold with no wrong mapping is
  **0.86: precision 9/9, recall 9/22**, all 5 "none" phrases unmatched. Kept as the rule says
  (no method tuning on these cases); the alias list carries the common phrases. For the PR.
- Deviations from §C (small, recorded): the alias list is checked right after the exact concept
  lookups, before `resolve_names`, so "F1" makes no model call at all (the plan's test "the
  alias path makes no model call"); a piece split on " and " that matches no part goes on whole;
  `onboarding_answered` is a map (concept → known) so screen 2 can resume with the answers;
  finish also clears `onboarding_picks`; know/pick refuse with 404 `not_offered` / 409
  `already_answered` / 409 `too_many_answers` / 409 `onboarding_done`; discover is refused (409)
  after finish; library fallback when fewer than 6 web items and nothing pending; resolve echoes
  each topic's redacted phrase (`phrase`) next to `phrase_index`; served items capped at 27.
- Also fixed: ruff errors in `scripts/landing_media_precheck.py` (committed earlier, CI would
  have failed).

- **Onboarding web built** (c0918ec): `WelcomePage` → `welcome/AboutScreen` (field, topics,
  free text in React state only, inline consent-v2, matches with "F1 → Sports" selects and
  removable concept chips), `welcome/DiscoverScreen` (cards, picks, Know this?, readback after 5
  answers, Edit, Start reading), `lib/onboardingApi.ts`, `lib/readback.ts`; the profile's
  onboarding block also returns `field` and `interests` (resume and Edit). Welcome chunk 5.1 KB gzip.
  vitest: readback, helpers, Continue disabled until field + topic + consent, free text only in
  React state and only in the resolve request after consent, screen 2 resume/picks/know/readback.
- **Harness run** (`tools/shots/onboarding.py`, emulators; 10 real searches: 9 topic + 1
  concept; resolve $0): axe 0 at 1440/390 light and dark on both screens. Found and fixed
  (dc21dd2): "Start reading" bounced back to /welcome (App gate kept a stale "not done"; now
  cleared when the flow finishes), readback said "more Sports" after two skips (likes minus
  skips per topic now), off-topic Know this? terms ("Column", "Action point", "OCT": now only the
  item's own topic, corpus concepts first), Know row wrapping at 390, chips 42px. Rerun: all
  green, feed topics economics, business, sports after two "Not for me" on Sports; the typed
  text appears nowhere in the API log.
- Docs: DESIGN §4, §8, §11.4, §17.1; STATUS §1, §4, §9, new §19; BUILD_PLAN M8 line; privacy
  page wording (resolved ideas aren't stored, only topics; setup lists cleared at finish).

- Sourabh (before the PR): extend the alias list to ~60 common phrases over all 14 topics and
  re-run the check. Now 109 entries (≈ 60 phrases plus variants; every topic covered, test).
  `evals/onboarding_topics.py` also scores the route's order (aliases first, then embedding at
  0.86): **10/22 recognised, 0 wrong**, the 5 "none" phrases unmatched (was 9/22). Only
  "smartphones" and "mutual funds" (both named by Sourabh) copy test phrases; without them 8/20,
  unchanged: the test phrases are longer variants that exact aliases don't match. One embed call
  per run ($0.00003 each, two runs). API tests 664.

- Sourabh: word-level matching for the topic fallback. `ot.word_topic`: words and adjacent
  2-word chunks (stop-words, generic words, bare country names dropped; possessives stripped),
  looked up in the alias list and concept labels; one-word concept chunks only with doc_freq > 0
  (decided before the run, so "Column"-like seed words can't map nonsense); strongest: 2-word,
  alias over concept, doc_freq, earlier. Rules fixed before running; nothing tuned after.
  Result: **18/22, 0 wrong, 5/5 nonsense unrecognised** (alias 2, words 13: 6 via aliases,
  7 via concepts; embedding 3). Caveat reported: the 6 single-word alias hits come from aliases
  added after the test set was seen; independent of the alias list, 10 of the other 14.
  The route test found that word matching ran after `resolve_names` (a model call for
  "cricket highlights"); moved before it, so model calls happen only when nothing matches.
  API tests 667.

- **milestone-reviewer: FIX** (5 items + follow-ups). Done: (1) privacy: several free-text
  pieces could share one `link_confirm` prompt (resolve_names batches names): now one
  resolve_names call and one embed request per piece; a test with two candidate pieces fails on
  the old code; DESIGN §11.4 says so. (2) STATUS §19 landing rows from my own run of
  `tools/shots/landing.py` (now asserts 0 network after load, axe 0 at every level, and a
  keyboard path); one mobile LCP figure: Lighthouse 12.8.2 × 3 on the final local build =
  2.6 s, perf 95 (the earlier 5.7/5.9 s unexplained; live run decides). (3) after shots committed
  (`docs/evidence/landing/after/`, JPEG subset; onboarding `after/`); deviations recorded: no
  "before" of the old welcome steps, no-flash checked by the boot switch. Keyboard run found a real
  issue: answered buttons were `disabled`, so focus fell to the page top; now `aria-disabled`,
  focus stays (harness: axe 0, keyboard all true). (4) `test/evalNumbers.test.ts` (evals.json
  equals the report; malformed tables throw). (5) STATUS §10 rows 46b, 46c, 46e, 47, 42b.
  Follow-ups done: finish needs screen 1 saved (409), topic chips capped at 6. API 669, web 52.

- milestone-reviewer **SHIP** (round 2). Edit refills ≤ 6 topics (c7892d8). PR #26, CI green,
  squash-merged (8a724e5). API deployed (revision 00021; the first deploy kept running after it
  was backgrounded, the second attempt was refused by deploy-guard, no double deploy) and web
  deployed, each on Sourabh's yes. Live anonymous check: all landing checks pass, 0 network after
  load, axe 0, keyboard pass; Lighthouse mobile live 1.2 / 2.0 / 1.8 s (median 1.8 s: passes the
  2.5 s gate, unlike the local preview's 2.6 s). Pending: Sourabh's Google onboarding.


## Decision 48 — topics in the older boxes, Redo setup (2026-10-11)

- Live check of #26: "Indian politics" failed as a learning goal and in Describe yourself
  (both only knew concepts and levels); Sourabh's account had finished the M7 onboarding, so
  the new screens never showed. Sourabh: decision 48 (plan `docs/plans/d48.md`).
- plan-reviewer: REVISE (15: module split, one embedding per phrase, alias before any model
  call, whole-token matching, one-step create, guarded undo, old edits, demo, topic cap, eval
  baseline on v5, done checks in transactions, keep comfort on redo, cancel route, schedule,
  injection case), all applied; APPROVE (nits applied: X05 forbids set_interest; the alias
  lookup runs twice in the goal path, documented).
- Evals (cases committed first, 9cab17f): v5 7/10 / 5/5; v6 9/10 (P11 direction empty); v7
  "direction always filled" 8/10 (worse); v6 + "empty = more" 10/10 then 9/10 (turned "less
  cricket" into more: dropped); v7 `read_more` / `read_less` ops 10/10 twice, attacks 5/5.
  Total ≈ $0.06 (spend counter). Found on the way: topic-eval results in `evals/results/`
  broke `report.py` (it reads results/*.json): moved to their own folder.
- Built: `app/me/topic_match.py`; topic goals (preview + save-resolved); `set_interest` with
  guarded undo; Redo setup (start, cancel, done kept, comfort/frames/θ kept); web goal preview,
  interest lines, Redo button, redo-aware welcome; finished readers outside a redo are sent
  home from /welcome; acronym know-terms need capitals. API 686, web 57.
- Harness (`tools/shots/d48.py`): all flows pass, axe 0 (STATUS §20). First run failed on my
  script (clicked the habit form's Add); fixed.

- milestone-reviewer FIX (interest-only history line blank; eval record; evidence; STATUS) → all
  fixed (f425072) → **SHIP**. PR #27, CI green, squash-merged (458ef05). API deployed (revision
  00022) and web deployed, each on Sourabh's yes. Sourabh: "Redo did work."

## Decisions 49 and 50 — feed first, then extension, then Wide layout (2026-10-11)

- Sourabh: extension before Wide layout (49); then "M7.5 should be finished before everything":
  the For you feed isn't up to mark (no Refresh after preference changes; small local papers).
  TinyFish setup was blocked by Claude Code's safety check (it writes MCP config into every coding
  agent on the machine); he can run it himself with `!`; not used for the feed (browser agent
  unsuited). Decision 50: top outlets' section feeds, twice-daily job ($0 expected), 40% global +
  60% reader's country, restricted search fallback, Refresh.
- Evidence before planning: section feeds checked (curl) and readability measured with our own
  safe_fetch + extract (BBC, Guardian, NPR, The Hindu, Indian Express, Mint, ET readable; ThePrint,
  Scroll empty; Nature RDF; Ars blocked; Al Jazeera short).
- Plan `docs/plans/d50.md` on branch `d50`: plan-reviewer REVISE (13) → APPROVE (nits applied).
- M8 prep done on local branch `m8-resume` (not pushed): the three M8 plan commits replayed onto
  main; the old docs commit for M2.2 skipped (superseded); the wip code commit 2f037a1 not replayed
  (7 conflicts, mostly superseded by M7.5's per-reader visibility); carry its redaction format,
  fixture and tests and the `extension` exclusions over by hand when M8 resumes.

### Next steps (resume here, in order)
1. **Decision 50** on branch `d50` (plan approved, `docs/plans/d50.md` incl. Round 1 + 2): build
   API (outlet registry + `outlet_feed.py` parsing moved from collect_corpus, `OutletStore`,
   internal collect endpoint with SA-email/aud/iss checks, mix 60/40, `feedx:` fallback with the
   constant include_domains, country field), web (country on screen 1 + Preferences, For you
   Refresh + `rl:feed-stale`, unset-country hint), `scripts/check_outlets.py`,
   `scripts/collect_outlets.py --dry-run`, `make setup-feed-job`; tests; harness; checkpoint end
   of Oct 12 IST with the cut order.
2. Demo personas read as India (decision 51, answered): `PERSONA_COUNTRY = "IN"`.
3. Review, PR, deploy order API → scheduler setup (his yes) → manual run → seed dry run → seed →
   web; live check on his account (country set, Refresh).
4. Then M8-local from `m8-resume`, then Wide layout.

### Decision 50 build (2026-10-11, branch d50)
- API (5ccbe6f): registry, `outlet_feed` (parsing moved from collect_corpus), `outlet_job` +
  `POST /v1/internal/feeds/collect` (Google OIDC claims, fails closed), `OutletStore`
  (`rec_cache/outlets:<topic>`), feed outlet-first with `feedx:` restricted fallback, 60/40
  `article_split`, `country` (onboarding, settings; demo 403), `PERSONA_COUNTRY = "IN"`.
- Scripts (d971ed5): `check_outlets` dropped Indian Express and Economic Times by the pre-set
  rule (evidence kept); `collect_outlets --dry-run`; seed_demo_feed from outlets; Makefile
  `setup-feed-job` / `run-feed-job` (one job, two times); deploy.env.yaml FEED_JOB_* vars.
- Web (74597a7): country on screen 1 (locale prefill) and Preferences, Refresh, `rl:feed-stale`,
  country hint, /privacy.
- Harness (28ddf91): STATUS §21. 9/9 registry articles, 5/4 mix, Refresh 0 searches, Redo
  in place, axe 0; Preferences overflow at 390 fixed. 5 of 6 sample articles ≥ 400 words.
- Tests: API 717, web 63. No LLM spend.

### Next steps (resume here, in order)
1. milestone-reviewer on d50 → fix until SHIP → PR → green CI → merge.
2. Deploy API (his yes) → `make setup-feed-job` (his yes) → `make run-feed-job` → seed dry run
   → seed → web deploy (his yes) → live check (his account: country, Refresh).
3. Then M8-local from `m8-resume`, then Wide layout.

### Decision 50 review
- milestone-reviewer round 1 FIX (3 blocking: fallback unmeasured, 60/40 broken by the
  24-item cut for 5–6 topics, STATUS stale; 4 non-blocking) → 6d21c82: select sizes the split
  over surviving slots (6-topic test, fails on old code); fallback 13/14 topics, 3/3 concepts
  → keep (43 Tavily credits); STATUS fixed; in-app country link; "Somewhere else" hint.
- Round 2: **SHIP**. Follow-ups: credits in §7/§5 (done), watch policy fallback live.
- Next: push d50, PR, green CI, merge; then the deploy sequence in STATUS §9.

### Decision 50 merged and deployed (2026-10-11)
- PR #28 squash-merged (cf87f7d) on green CI after SHIP.
- API deploy 00023 failed to start (feedparser dev-only); traffic stayed on 00022. Fix #29
  (89cb0ab) + guard test; API 00024 live; collect route 403 unauthenticated.
- Sourabh: "no one is using the site, deploy web parallely and schedule too": web deployed
  alongside the API (deploy guard skipped for the web step only), `make setup-feed-job` done.
- `make run-feed-job`: 200, 54/54 feeds, 710 items, 14 docs. Demo seed dry run → real (3 docs).
- Next: Sourabh's live check (country, Refresh); then M8-local from `m8-resume`, then Wide layout.
- 2026-10-12: scheduled runs 06:00 IST (703 items) and 18:00 IST (720), 54/54 feeds each. Live
  `feed mix` logs: a country-set reader, 4 local / 2 global of 6. d50 done.

### Next steps (resume here, in order)
1. M8-local from local branch `m8-resume` (plan amendment first: annotator 0.7, per-reader
   visibility, onboarding redirect; carry over wip 2f037a1's redaction format, fixture, tests and
   `extension` NOT_CORPUS exclusions by hand). Plan → plan-reviewer loop → build.
2. Then Wide layout (decision 45). Follow-ups on the M9 list: Telugu-title video, policy fallback
   thin, bundle headroom 2.4 KB.

## M8-local (resumed 2026-10-12, branch m8-resume)

### Plan amendment
- `m8-resume` was an ancestor of main: fast-forwarded to 0ba30e1. The approved Oct 10 plan
  (5d6d00f) amended for today's main: annotator 0.8 (`styles: "external"`, CSS via
  `insertCSS`), per-reader visibility (M7.5 built most of it), onboarding gate, wip 2f037a1
  carried by hand (redaction format + fixture + tests, three remaining `is_corpus` exclusions).
- plan-reviewer round 1: **REVISE** (12). My round-1 text started from the pre-approval draft on
  main and dropped approved items (`ext:` id, Presidio evidence, token/URL safeguards, approved
  acceptance): all restored. New: extension text readable only by its submitters (+ a text hash
  in the `ext:` id), typed-mode redaction keeps the broad catch, `/connect` survives the
  onboarding gate, `renderPreread` styles, token sheet, bundle budget.
- Round 2: **REVISE** (2): same reader reuses their own `ext:` doc; refusals before `insertCSS`.
- Round 3: **APPROVE** (nits applied, d79bab9).

### Next steps (resume here, in order)
1. Build on `m8-resume`: A2/A5 carry-over commit first, then API (A1, A3, A5 read gate, A6),
   annotator 0.8, extension, web `/connect`, README; tests; harness; checkpoint end of Oct 13 IST.

### Build (2026-10-12)
- 54d23ae carry-over from 2f037a1 (redaction format, fixture, typed mode, NOT_CORPUS exclusions).
- 7056293 A1 + A6: `ext:` id per URL and text, fetch doc wins, same-reader reuse, `defer`,
  `add_ingested` on every path, `pii_found_before_backstop`, 409 `onboarding_required`.
- 42d40fd A5 read gate (6 routes; mutation check: 5 tests fail with the gate off).
- 9cca874 PII fixtures frozen first. Then measured (read-only export of 338 stored docs, 323
  fetch + 15 user_ingested, 12,369 paragraphs; `scripts/export_corpus_text`, `measure_pii`):
  - Strict redactor: 10 paragraphs changed; 9 journalists' contact emails (real), 1 false
    positive (a 14-digit timestamp passing Luhn as a card) → ungrouped card runs now need an
    issuer prefix → 9 changed, all real contact data. Timestamp added to the shared fixture.
  - Presidio: phones score exactly 0.4; PAN hits below 0.5 are its catch-all pattern lifted by
    context (up to 19 per 1,000 words in ordinary articles). Policy: phones from 0.4, others
    from 0.5. Corpus max 3.98 per 1,000 words (contact emails), 34/338 with any finding, ≤ 1
    card. Fixtures: refuse 110 and 79, pass ≤ 6.9. Threshold 20 per 1,000 words with ≥ 3
    findings, or ≥ 3 cards → **0 of 338 corpus articles refused**.
  - Emails at `.example` aren't found (tldextract rejects non-public suffixes); the frozen
    fixtures still refuse on phones. Client placeholders count as findings, so a page the
    extension already redacted is still refused (test).
  - Analyzer build 0.58 s, max RSS 165 MB (Cloud Run 1 GiB); a 1,350-word article scans in
    0.2 s (runs in a thread). Built-in Aadhaar (Verhoeff) and PAN recognizers used instead of
    hand-written regexes. Offline test counts socket attempts (tldextract falls back silently).
- 7a20ee0..1c81ef8: CORS test; annotator 0.8.0 (`styles: "external"`, `ANNOTATOR_CSS`); extension
  (pure modules + jsdom tests, worker/content/popup, build + manifest check, stable id from a
  public key, private key discarded); the extension is **Gloss** (decision 40: name, Margo icon,
  real tokens; popup buttons ink pills, the teal accent only means a note); web `/connect` (lazy,
  under the gate, remembered through `/welcome`, "Use Gloss on any site" in the account menu);
  `make extension-config`, CORS origin in deploy.env, harness CORS; README install steps.
  Added beyond the plan: sign-in hosts refused (a signed-out Gmail tab lands on one).
- TypeScript redactor over the corpus export: the same 9 paragraphs as Python, all contact emails.
- Harness `tools/shots/m8.py` (STATUS §22): branded Chrome 154 ignores `--load-extension`
  (checked), so Chrome for Testing 153; `Extensions.triggerAction` needs the tab target id. Runs
  1–6 failed on the harness itself (buffered output, first navigation of a fresh profile not
  confirmed, popup can't take a metrics override, SW response bodies evicted → Fetch
  interception, error-page tab lookup, emulator rules → "Bearer owner"). Two real findings:
  `pii_found_before_backstop` counted the client's own placeholders (fixed + test); the design
  pass showed heavy dark marks on a light page under a dark OS (notes now follow the page's
  background) and the toast over the phone bottom sheet (toast at the top on phones).
  Final run: all 8 acceptance checks pass; harness spend ≈ $0.16 over all runs.
- Publisher-page overlay shots kept local (gitignored), STATUS §4.

### Next steps (resume here, in order)
1. milestone-reviewer on `m8-resume` → fix until SHIP → push, PR `M8: …`, green CI, merge.
2. Deploy API (his yes) → check the Firebase web key's restrictions allow the extension origin →
   deploy web (his yes) → `pnpm --filter extension build` → live check:
   one demo reader, 1 page not in the library (dry run first), test reader deleted after;
   Sourabh's manual Gmail and bank-login refusals. Then STATUS §1/§22 live rows.
3. Then Wide layout (decision 45).

### M8 review
- milestone-reviewer round 1: **FIX** (4 blocking: Presidio cost unbounded at the 150k-char
  maximum; README install needed gcloud; sign-out/delete left the extension holding the token;
  STATUS stale; 7 more). Applied: 346422d chunked Presidio (1.6 s / 201 MB at the maximum; a
  test caught a chunk reorder), 0e34069 Firebase web key via the Connect page + public build
  settings committed + sign-out disconnects + persona allowlist + retry after a failed read,
  3d5d355 server redacts title and URL query, dd300ed Unicode-digit and email parity (corpus
  check unchanged), privacy page, STATUS (header, §2, §4, §5, §7, §22). Not changed: `reusable`
  cost and live pages reused per reader (STATUS §5).
- milestone-reviewer round 2: **FIX** (2, both evidence: no end-to-end run on the final code;
  stale bundle numbers). Harness re-run on 8f6d4d7: every check passes with the same counts,
  $0.00; evidence refreshed. Bundle 148.08 KB main / 1.40 KB Connect. Also: emails need a
  lettered last label ("10@2.5" stays; corpus check unchanged).
- Sourabh (2026-10-12): yes to a ready-made extension zip for judges → `make extension-zip`
  (151 KB), README links the latest release; the release is created after the merge.
- milestone-reviewer round 3: **SHIP** (699a5c6). Follow-ups in STATUS §9: release zip, token
  refresh exercised in the live check, Firebase key restrictions, BBC shot retake.

### Next steps (resume here, in order)
1. Push `m8-resume`, PR `M8: …`, green CI, squash-merge (pre-approved after SHIP + green CI).
2. Deploy API (his yes) → check the Firebase web key's restrictions → deploy web (his yes) →
   `pnpm --filter extension build` → live check (1 page, dry run first, test reader deleted;
   force one token refresh) → Sourabh's manual Gmail and bank refusals → `make extension-zip`
   and the GitHub release → STATUS §1/§22 live rows.
3. Then Wide layout (decision 45; 1.9 KB of bundle headroom).

### M8 merged (2026-10-12)
- Pushed `m8-resume`, PR #30, CI green (api, typescript incl. the extension build), squash-merged
  (189fe7f) after SHIP. Firebase browser key: no referrer restriction, securetoken allowed.
- Not deployed yet. The emulator harness is stopped.

### Next steps (resume here, in order)
1. `make deploy-api` (his yes) → smoke: healthz, a submitted body from an unauthenticated caller
   is 401, CORS preflight from the extension origin → `make deploy-web` (his yes).
2. `pnpm --filter extension build` → live check: dry run (neither id exists), one demo reader,
   https://en.wikipedia.org/wiki/Term_structure_of_interest_rates, one forced token refresh,
   test reader deleted → Sourabh's manual Gmail and bank-login refusals.
3. `make extension-zip` → GitHub release with the zip (his yes) → STATUS §1/§22 live rows.
4. Then Wide layout (decision 45; 1.9 KB of bundle headroom).

### M8 API deployed (2026-10-12)
- `make deploy-api` on Sourabh's yes: revision `readlayer-api-00025-cf4`, 100% of traffic.
  Smoke: /health 200; unauthenticated submitted body 401; CORS preflight 200 for the extension
  origin and the Hosting origin, 400 for another extension's origin; startup log clean (graph
  2026-10-10-folded-5206+g1 in 1.0 s); no warnings beyond the smoke requests.
- Next: `make deploy-web` (his yes), then the live check, the manual refusals and the release zip.

### M8 live (2026-10-12)
- `make deploy-web` on Sourabh's yes; live `/connect` and the account-menu item verified.
- Live check run 1 (the plan's Wikipedia page): passed, but the page redirects to "Yield curve",
  already a corpus doc, so the fetch doc was reused and no `ext:` doc or Presidio run happened
  in production. My dry run had checked the pre-redirect URL: follow redirects in dry runs.
- Sourabh: yes to a second throwaway demo reader. Run 2 (an NPR article, dry run with
  redirects): new `extension` doc 84c9a717… (22 paragraphs, $0.0027), Presidio ran live, forced
  token refresh 200, test reader deleted. STATUS §22 "Live" row.

### Next steps (resume here, in order)
1. `make extension-zip` → GitHub release with the zip (Sourabh said yes) → push the docs commits.
2. Sourabh's manual check: his Gmail tab and a real bank login page are refused.
3. Then Wide layout (decision 45; 1.9 KB of bundle headroom).
- Release `extension-v0.8.0` on main (02c0bdd) with `gloss-extension.zip` (production build,
  manifest: activeTab, scripting, storage; the two Hosting origins). Docs pushed to main.

### Next steps (resume here, in order)
1. Sourabh's manual check with the release zip: his Gmail tab and a real bank login page are
   refused with the popup message (STATUS §22 acceptance 2, the only open M8 item).
2. Wide layout (decision 45): own plan in `docs/plans/`, plan-reviewer loop, build. Main bundle
   headroom is 1.9 KB.
3. M9 hardening (Oct 15), freeze Oct 16.

## Wide layout (decision 45) — plan (2026-10-13)

- Resumed after /clear. Sourabh's manual Gmail and bank-login refusal check is still open (asked
  again at the start of this session); it does not block this work.
- Plan `docs/plans/wide-layout.md`, branch `wide-layout`. Web only: no API, Firestore, prompt,
  model or annotator-package change; the only production action is `make deploy-web` (his yes).
- plan-reviewer round 1: **REVISE** (13 items + 3 nits): reader clamps overflowed at 1280; the
  sidenote check assumed the card is as wide as the rail (it is sized from the window edge); spine
  fill and ticks in different coordinate systems; `Anchor.start` is already article-level; feed
  rows narrower than today at 1440; the map not actually taller; the ellipse changing the 760
  canvas phones use; `layout()` unusable at 300×230; the map link dropping the demo persona;
  four harness gaps (incl. a before run); automatic cuts; recording; the bundle fallback.
  Round 2: **REVISE** (3 + 2): the spine needs its own progress function (`placeInArticle`);
  acceptance 3 must ignore the "Know this?" chip's own text; record the tile grid. Round 3:
  **APPROVE**. Every item applied; the round sections at the end of the plan override its body.
- **Two readings of decision 45's words, flagged to Sourabh in the session, both in STATUS §4
  and §10:** (1) the reader's left-rail "contents" is a **reading spine** (a track of the article
  with a tick per note, the read part filled, notes count, minutes left) because articles have
  no headings; (2) the library's "mini-map" is a **grid of topic tiles** (one cluster of dots per
  topic), not a small copy of the full map, which is not legible at 240–280px. Two more
  deviations: the container is 1520px from 1440px; This week moves beside Goals above the map
  (not in decision 45, dropped first if late).
- Baseline before any change (`pnpm --filter web build`): main JS **148.08 KB** gzip, main CSS
  10.85 KB, profile chunk 10.01 KB JS / 3.30 KB CSS.

### Next steps (resume here, in order)
1. `tools/shots/wide.py` with `--before`; run it on the unchanged web code into
   `docs/evidence/wide/before/` (emulators; the Google reader seeded with 6 topics and 3 goals).
2. Build in the plan's order, tests first for the pure helpers: snapshot of today's `layout()`
   → `mapSize` and the ellipse; `lib/weekMap.ts`; `lib/spine.ts` and `lib/readingProgress.ts`;
   then tokens and library, profile, reader. Check the main bundle after each page.
3. Harness run with assertions, design check on the shots, milestone-reviewer until SHIP, PR
   (body names the four deviations), green CI, merge, `make deploy-web` (his yes), live check.
4. Checkpoint end of Oct 14 IST: not merged → ask Sourabh what to cut. Then M9 (Oct 15).

## Wide layout (decision 45) — built (2026-10-13)

- 3c13084 the 760px map snapshot before any change; 3b707e1 `tools/shots/wide.py` and the
  **before run** (rows 720px from 1280, map 798×630 scaled 1.05, six topic cards 4 + 2 with a
  grey cell, reader grid 1044px; three moderate axe findings the older harness filtered out).
  An orphaned Firestore emulator from the M8 harness (java on :8085, parent gone) was stopped
  first so the stack could start.
- Built in the plan's order, pure helpers test-first: `mapSize` and the ellipse above 760px
  (the pinned 760 snapshots still match; dots no longer pile on the edges: clamping now takes
  part in every pass on the wide path), `lib/weekMap.ts`, `lib/spine.ts`,
  `lib/readingProgress.ts`, `cardColumns`; then tokens, profile, library (two sidebar groups,
  lazy `WeekPanel`), reader (lazy `ReadingSpine`, `railColumn` on `clientWidth`).
- Harness on the final code: **0 failed checks**, axe 0 at every impact level on 85 states,
  main bundle 148.32 KB. STATUS §23 has the numbers and what changed from the plan.
- Three things the harness caught that screenshots alone would not: the Read any link field
  overflowing the narrower sidebar; a new reader's first library load taking ≈ 20 s on the
  emulator once a fourth request raced the others to create the user record (the map request
  now waits for the library's first answer; STATUS §5); and a headless page going "hidden"
  after a key press, which froze transitions and looked like an app bug.

## Extension shows no notes on a Hindu article (Sourabh, 2026-10-13, mid-session)

- Not site-specific and not an error. Production logs for his four clicks (19:08–19:11 UTC):
  every request 200, the article read as 11 paragraphs, but demands linked 1/18, 0/8, 1/45 and
  2/8 and **no concept growth ran**. Earlier that evening five articles he opened each reserved 5
  growth slots (25 = his daily cap) while adding 17 concepts; slots are never returned.
- Told him in the session with a three-part proposal (return unused slots, raise the caps,
  grow again on reopen plus an honest message). **Waiting for his answer** before touching the
  caps (cost guardrails, decision 35). STATUS §5, first row.

### Next steps (resume here, in order)
1. Sourabh's answers: (a) the extension fix above: now, or first item of M9; (b) the two
   readings of decision 45 (reading spine, topic tiles); (c) his manual Gmail and bank-login
   refusal check (still the only open M8 item).
2. Wide layout: milestone-reviewer on `wide-layout` → fix until SHIP → push, PR `Wide layout: …`
   (body names the four deviations), green CI, merge → `make deploy-web` (his yes) → live check
   at 1440 as a demo reader, and his own look at the three pages.
3. The emulator stack is running from this session (`make dev-emulator`, log in the session's
   scratchpad); stop it when the review is done.
4. M9 (Oct 15), freeze Oct 16.

## Wide layout — milestone review round 1 (2026-10-13, evening)

- milestone-reviewer on 6d81e18: **FIX**, 5 blocking: the map drawn 680px tall in the stacked
  440px canvas at 866–960px (a half-screen window on a 1920 display; the harness only had 390
  and 1024); the tile "N ideas" count was the overview's capped length, contradicting the
  profile's cards; the rules between topic cards gone; "nothing changed at 390" contradicted by
  the shots and never measured at tablet widths; STATUS stale in four places. Five more, all
  taken: sticky groups at any height, a state with risen ideas, a boundary around the lazy
  parts, the 960/961 breakpoint, the schedule.
- The session ended overnight with the fixes on disk, uncommitted; resumed in the evening
  (Sourabh: "continue"). Restarted the emulator stack.
- Before run at tablet widths: the fixes stashed, `apps/web/src` checked out at 3b707e1,
  `wide.py --before --narrow`, tree restored (same 13 paths, stash empty).
- Harness on the fixed code: **0 failed checks**, axe 0 on 110 states (tablet widths, sticky
  at 1440×900 and 1440×760, the risers state). Main bundle 148.43 KB. STATUS §23 rewritten;
  the two readings in §4 are marked open until Sourabh answers.
- Sourabh asked for a check of the background tasks during the run: stack and harness running,
  nothing orphaned.

### Next steps (resume here, in order)
1. milestone-reviewer round 2 on the fix commit → until SHIP.
2. Sourabh's answers: the two readings (reading spine, topic tiles) before the deploy; the
   extension fix (STATUS §5 first row): now, or first item of M9; his Gmail and bank-login
   refusal check.
3. Push `wide-layout`, PR `Wide layout: …` (body names the four deviations), green CI, merge,
   `make deploy-web` (his yes), live check at 1440 as a demo reader.
4. Stop the emulator stack (`make dev-emulator`, started this evening). M9 Oct 15, freeze Oct 16.

## Growth caps raised (decision 53, 2026-10-13, evening)

- Sourabh: "if the three items can be done in next 10 minutes then go yes else wait". Told him
  the extension fix is an hour or two (API change, tests, plan review, deploy, a new zip), not
  ten minutes, and that only the cap raise is quick. His answer: **"just cap raise now"**.
- Identity checked, then `gcloud run services update readlayer-api --update-env-vars
  GROWTH_PER_UID_DAY=60,GROWTH_PER_DAY=300` (his yes on the prompt): revision
  `readlayer-api-00026-wc2`, 100% of traffic, same image, 21 env vars, max instances 3.
  Smoke: /health 200, unauthenticated profile 401, startup clean (graph
  2026-10-10-folded-5206+g1 in 1.3 s), no warnings beyond the smoke request.
- Also written to `apps/api/deploy.env.yaml` so the next `make deploy-api` keeps it; STATUS §5
  first row, §7, §10 decision 53. The code defaults (25 / 100) are unchanged.
- Not done, M9: return unused slots, grow again on reopen (his four pages stay empty), the
  honest message.

## Wide layout — milestone review round 2 (2026-10-13, evening)

- milestone-reviewer on a9da102: **FIX**, 1 blocking. Every round-1 item confirmed fixed (it
  swept the map at 16 widths and scanned the shots for the card rules). The blocker: the
  panel's "+N this week", its line and its labels were counted from the overview's nodes, which
  are a topic's top 12 by band then frequency, so a rise outside them was invisible and the
  panel could say "Nothing moved up" while the profile listed moves. The harness state had only
  shown the constructed case (two corrections land at the top of the list).
- Fix: the week's numbers come from `GET /v1/me/profile` `week.moved_up` (uncapped); the
  overview only draws the dots. Unit and component tests with a rise the overview doesn't
  carry; the harness asserts the panel's count equals the profile's list.
- Also taken: ring quota capped at the room left, rings sized so two neighbours don't cross,
  "We think you know" in the key, the last block's margin in a sticky group, the Saved tab,
  search and Connect in the harness (which found `role="status"` on Connect's heading, a minor
  axe finding from M8: now a span inside it), a seven-topic reader (cards 4 + 3, 7 at 1920).
- Harness on the final code: **0 failed checks**, axe 0 on 123 states. Main bundle 148.43 KB,
  week panel 1.68 KB. Web tests 148.

### Next steps (resume here, in order)
1. milestone-reviewer round 3 → until SHIP.
2. Sourabh's answers: the two readings (reading spine, topic tiles) before the web deploy; his
   Gmail and bank-login refusal check. The rest of the extension fix is M9's first item.
3. Push `wide-layout`, PR `Wide layout: …` (body names the four deviations and the
   `deploy.env.yaml` caps), green CI, merge, `make deploy-web` (his yes), live check at 1440.
4. Stop the emulator stack (`make dev-emulator`, started this evening). M9 Oct 15, freeze Oct 16.

## Wide layout — milestone review round 3 (2026-10-13, late evening)

- milestone-reviewer on 59261f7: **FIX, docs only**; no code change and no harness re-run asked
  for. The layout work and the round-2 fix stand. Five statements corrected: DESIGN §2's growth
  caps (defaults 25 / 100, production 60 / 300); a STATUS §5 row on anonymous traffic (at most
  150 of 300); a §6 row and a §8 line for the growth settings; the cost of the higher caps, which
  I had given Sourabh as "about thirty-five cents a day" without a source (logged range: $0.3 to
  $0.5 at most); §23 row 1a″ (no top-bar check runs on Connect).
- Its recommendation, not taken: move the caps commit (3fcda42) to its own PR. Kept on this
  branch to avoid a second push, CI run and a rebase of the docs two days before the freeze;
  the PR's first line will name it, STATUS §23 and §1 say so, and the branch merges before any
  API deploy. Sourabh can ask for the split.
- Three cosmetic points left as they are (STATUS §5). Sourabh's answer on the two readings is now
  wanted before the merge, not just before the deploy.

### Next steps (resume here, in order)
1. milestone-reviewer round 4 (doc diff only) → SHIP.
2. Ask Sourabh again: the two readings (before the merge); push and PR (his yes).
3. PR `Wide layout: … (+ growth caps, decision 53)`, green CI, merge, `make deploy-web` (his
   yes), live check at 1440. No API deploy before this merges.
4. Stop the emulator stack. M9 Oct 15 (first item: the rest of the extension fix), freeze Oct 16.

## Wide layout — milestone review round 4, and Sourabh's yes (2026-10-13, late evening)

- **Sourabh said "yes"** to the two readings asked together (the reading spine as the reader's
  left rail; topic tiles as the library's mini-map). STATUS §4 rows are now "Keep".
- milestone-reviewer on 9d99133: **FIX, docs only**. Two statements wrong: "at most 150 of the
  300" for anonymous traffic (its own round-3 wording; false, because growth slots are reserved
  before the fetch and kept when it fails: its local probe took the day's counter to 300 with
  60 failed opens and no spend), and the cost "at most" (6 of 14 paid runs). Checked the 14 runs
  in the production log again: $0.0024 to $0.0127, mean $0.0050, $0.070 for 50 concepts.
- **New risk recorded, STATUS §5 Medium:** 60 failed link opens by anonymous readers stop growth
  for everyone until 00:00 UTC. M2.2 behaviour; it goes with the rest of the growth fix as M9's
  first item. Told Sourabh.
- BUILD_PLAN's "before M8" wording brought in line with decision 49.

### Next steps (resume here, in order)
1. milestone-reviewer round 5 (`git show` of the fix commit) → SHIP.
2. Push `wide-layout` and open the PR (his yes on the prompt): `Wide layout: … (+ growth caps,
   decision 53)`; green CI; merge; `make deploy-web` (his yes); live check at 1440.
3. No API deploy before that merge. Stop the emulator stack.
4. M9 Oct 15, first item the growth and extension fix; freeze Oct 16. Sourabh's Gmail and
   bank-login refusal check is still open.

## Wide layout — milestone review round 5: SHIP (2026-10-13, night)

- milestone-reviewer on 9158161: **SHIP**. It re-ran typecheck, web 148 / annotator 57 /
  extension 85, API pytest (789 passed, 2 skipped), ruff and the build (148.43 KB), and checked
  the cost figures against the production log and the caps on the live service.
- Emulator stack stopped. Next: push and PR (Sourabh's yes on the prompt).

### Next steps (resume here, in order)
1. Push `wide-layout`, PR `Wide layout: … (+ growth caps, decision 53)`; the body states the
   two readings in plain words, the four deviations and the settings commit. Green CI → merge.
2. `make deploy-web` from up-to-date main (his yes) → live check at 1440 as a demo reader →
   STATUS §23 live row. No API deploy before the merge.
3. M9 (Oct 15): plan with a cut order; first the growth and extension fix (refund on a failed
   fetch and regrowth on reopen protect the demo). Freeze Oct 16.
4. Still open from M8: Sourabh's Gmail and bank-login refusal check.

## Wide layout merged (2026-10-13, night)

- Pushed `wide-layout`, PR #31, CI green (api 47 s, typescript 1 m 15 s), squash-merged
  (13d9772). `main` now carries decision 53's caps in `deploy.env.yaml`, so an API deploy is
  safe again. The emulator stack is stopped.
- Sourabh, as the merge finished: next he wants **videos and podcasts readable in Gloss, with
  the transcript analysed like an article** (meaning before and after). Not in BUILD_PLAN; the
  freeze is Oct 16 and M9 (Oct 15) holds the growth fix. Asked him how to fit it (below).

### Next steps (resume here, in order)
1. `make deploy-web` (his yes) → live check at 1440 as a demo reader → STATUS §23 live row.
2. His decision on the video and podcast feature: scope and what it displaces.
3. M9 (Oct 15): plan with a cut order; first the growth and extension fix. Freeze Oct 16.
4. Still open from M8: his Gmail and bank-login refusal check.

## Wide layout live (2026-10-13, night)

- `make deploy-web` on Sourabh's yes; the live site serves `index-D-bYE-YM.js`. Live check at
  1440 with one throwaway demo reader, reads only: library, profile and reader as on the
  harness (STATUS §23 "Live" row); the reader deleted through "End demo".
- Wide layout is done: merged, deployed, STATUS and this log updated.

### Next steps (resume here, in order)
1. Sourabh's decision on the video and podcast feature (asked: scope and what it displaces).
2. M9 (Oct 15): plan with a cut order; first the growth and extension fix. Freeze Oct 16.
3. Still open from M8: his Gmail and bank-login refusal check.

## Decision 54 — videos and audio next (Sourabh, 2026-10-13, night)

- His words: "next I want youtube and audio please", after I had laid out three options and
  recommended a YouTube-only slice. So both, next, before M9. Recorded: STATUS §9 and §10,
  BUILD_PLAN "Media" (a draft prompt in his terms and what the plan has to settle).
- Unanswered: whether paying per item for Gemini to read the media is fine (default yes, capped),
  and the calendar trade (default: Oct 14 with a checkpoint at the end of the day; M9's growth
  fix stays Oct 15).
- Nothing built yet. Wide layout is fully closed (merged, live, logged).

### Next steps (resume here, in order)
1. **Media plan**: read DESIGN §3, §7, §9, §16–17 and `app/ingest/`, `app/recs/`, the reader
   page; measure Gemini on one YouTube URL and one podcast file (tokens, cost, time) before
   fixing caps; write `docs/plans/media.md`; plan-reviewer until APPROVE; then build on a branch.
2. M9 (Oct 15): plan with a cut order; first the growth and extension fix. Freeze Oct 16.
3. Still open from M8: his Gmail and bank-login refusal check.


## Media — measured, plan drafted (2026-10-13, late night)

- Measured Gemini on Vertex on real items before fixing caps (scratch script, not committed;
  budget check before and ledger write after each call): 15 paid calls, **$0.56** in the
  ledger (day $0.65 of $8). Two temporary audio objects in the graph bucket, both deleted
  (Sourabh's yes on each). Table and conclusions in `docs/plans/media.md` "Evidence".
- What it settled: transcripts on `MODEL_QUALITY` at low thinking (the fast model dropped a
  third of the speech on a window, twice, with no error); ten-minute windows (one call on a
  68-min video overran the output limit and looped); about **$0.025 per 10 minutes**; podcasts
  as MP3 pieces sent inline (links work only for small files, offsets are ignored on audio, no
  bucket needed); LiteLLM 1.104 leaves audio tokens out of its cost, so `llm.py` must add them.
- Cached results: 95% of videos ≤ 30 min; podcasts are mostly Apple show pages and Spotify;
  only Apple episode links resolve to audio (15 of 19, 13 MP3). No CSP exists on the site.
- Plan written: `docs/plans/media.md`. First plan-reviewer run was cut off by the session limit;
  re-running.
- Sourabh said **"yes"** to paying per recording (about $0.025 per 10 minutes, capped, inside
  $8). Recorded in the plan's decision 1.
- Plan-reviewer round 1: REVISE, 15 items, all applied (plan section "Round 1"). Audio has no
  price in LiteLLM and none was found on Vertex's page, so audio is priced by an override at
  $2.50 per 1M (cautious guess; about $0.05 per 10 minutes). Sourabh, asked to check the
  billing SKU: **"mark 3 dollar budget"**: `MEDIA_DAILY_BUDGET_USD = 3` inside the $8, no
  billing check. Round 2 running.

- Round 2: REVISE, 5 items, all applied. Round 3: **APPROVE** (2026-10-14, just after
  midnight IST); its two nits applied. Plan and log committed on `main` as docs.

### Next steps (resume here, in order)
1. Branch `media` from `main`. Build in the plan's order ("Schedule and cut order", reordered
   in round 1): frozen transcript cases first (R13), then YouTube end to end, harness run on
   the 16-minute video, web; **midday check-in with Sourabh** before podcasts; podcasts behind
   `MEDIA_AUDIO_ENABLED`. Read the plan's Round 1 and Round 2 sections first: they override the
   earlier ones.
2. Checkpoint end of Oct 14 IST: not merged → ask Sourabh what to cut (decision 27).
3. M9 (Oct 15): growth and extension fix first. Freeze Oct 16.
4. Still open from M8: Sourabh's Gmail and bank-login refusal check.

## Media build, step 1 (2026-10-14)

- Branch `media` from `main`. First commit: `evals/cases/media_transcripts.yaml` frozen (R13):
  the 16-min video, the 22-min Apple episode, the 50:00–60:00 window of the 68-min video, with
  the measured references (no transcript text kept).
- `llm.transcribe` (task `transcribe`, `transcribe-v1` = the measured wording): quality model,
  low thinking, 8,000 tokens, 90 s, no fallback; one unchanged re-ask on invalid output (schema,
  the window check, or cut off at the limit); a timed-out or cancelled call is charged its
  window's estimate; a shared `MediaMeter` carries what a failed run cost (R2). Both budgets
  checked per call (`check_media_budget`: the $8 and the $3 media share; the ledger gains
  `media_usd`).
- **Pricing differs from the plan's §D wording, matches R6:** checked locally that LiteLLM 1.104's
  `completion_cost`, given a response that splits out text tokens, prices only those and drops
  video as well as audio. So media calls are priced by us from the token counts: (input − audio)
  at the input price, audio at LiteLLM's audio price or `MODEL_AUDIO_PRICE_OVERRIDES`, output at
  the output price; no audio price → refused before the call. Test pins row 11 ($0.0247 with
  audio at the text price; $0.0509 at $2.50 per 1M).
- `app/media/transcript.py` (pure): window plan, clock parsing, per-window check (absolute or
  relative times, loops, > 300 words a minute, monotone), language majority, cross-window join,
  short-paragraph merges, the 200-paragraph cap by merging, `no_speech`, `not_english`,
  `too_long`; words-unchanged test. Media settings added to `config.py` (not yet in
  `deploy.env.yaml`: that comes with the caps step).
- API suite 838 passed, ruff clean.

### Next steps (resume here, in order)
1. Step 2 of the plan's schedule: `app/media/urls.py` (classify, canonical ids) and YouTube
   `videos.list` with its refusals and the `media_lookup` counter → `app/media/service.py`
   (stages, windows stored as they finish, lease token, refusal memory, the per-item ceiling) →
   caps → routes (`/v1/recs/open` media branch, `/v1/content/{id}/transcribe`, GET fields) and
   the POST /v1/content `use_open_here` guard (R4). Plan's Round 1 and 2 sections override.
2. Then the harness run on the 16-minute video; web; midday check-in with Sourabh before podcasts.
3. Checkpoint end of Oct 14 IST: not merged → ask Sourabh what to cut (decision 27).

## Media build, step 2 (2026-10-14)

- **YouTube end to end in the API**, offline-tested with fakes (no paid call yet):
  `app/media/urls.py` (classify, canonical ids), `sources.py` (`videos.list`: not public,
  not embeddable, age-restricted, live, < 30 s, > `MEDIA_MAX_VIDEO_S`, non-English audio or
  title), `refusals.py` (codes and reader messages), `service.py` (open: cached → remembered
  refusal → pending → slot → lookup cap → lookup → media budget → `create_media`; transcribe:
  budget pre-check for the missing windows, staged lease with token, window 1 alone when the
  language is unknown, four windows at a time under the 2× ceiling (`too_costly`), each window
  saved as it finishes, assembly, `finish_transcript`), `openable.py` (`open_here`),
  `store/media_repo.py` (day map of refusals, demo count, `media_lookup` on the search day doc
  without touching `calls`). `media_counts` added to `USER_SUBCOLLECTIONS`.
- Routes: `/v1/recs/open` media branch (`kind`, `stage`; 422 per code, 429
  `media_cap_reached`, 503 `media_unavailable` (new code: a failed lookup, not remembered) or
  `llm_budget_exceeded`); `POST /v1/content/{id}/transcribe` (200, 202, 404, 410, 422, 503, 504);
  GET content: `status` transcribing / analysing / ready / refused / failed, `media`, `refusal`,
  `start_s`; library rows `format`; feed and recommendations items `open_here`; POST /v1/content
  422 `use_open_here` for both shapes; analyse on a transcribe-stage doc 409
  `content_transcribing`. Phase 2 copies `media` and `start_s` and lists the transcribe calls.
- `deploy.env.yaml` gains the media lines and the $2.50 per 1M audio price.
- Choices to flag at review: transcribe uses analyse's access rule (any signed-in reader may
  continue a recording someone opened; the slot was taken at open). GET status "failed" now also
  shows for an *article* whose analysis attempts are used up (was "analysing"); the web must
  handle it in step 4. Podcasts: `open_media` answers `media_off` and `open_here` is false until
  step 6.

### Next steps (resume here, in order)
1. Step 3, harness run on real Vertex (`make dev-emulator`): open the 16-minute video
   (`d6fUwCBvVc0`) through Read any link; acceptance 1–3, video half (words ±10% of 1,822, last
   start ≥ 15:00, transcribe ≤ $0.10, phase timings, two personas, a verified card), a second
   reader free, refusals (Hindi video, 68-min video, Spotify, `MEDIA_ENABLED=false`, caps).
   Check the emulator's spend ledger is the emulator's, and state the expected cost (≤ $0.20)
   before running.
2. Step 4, web: lazy `MediaReader`, click-to-load player, time buttons, follow, entry points,
   "failed" status; then shots. Then the midday check-in with Sourabh before podcasts.
3. Checkpoint end of Oct 14 IST: not merged → ask Sourabh what to cut (decision 27).

## Media build, step 3 (2026-10-14, in progress, stopped for Sourabh)

- Harness up (`make dev-emulator`); seeded production spend $0.6543, harness budget $1.6543;
  the emulator ledger is the emulator's (read back after seeding).
- `dev_emulator.sh` now passes production's `MODEL_AUDIO_PRICE_OVERRIDES` to the local API: the
  first transcribe was refused before any call ("no media price for model"), $0 (R6 guard works).
- **Acceptance 1 fails on the 16-min video.** videos.list says PT16M (960 s); the measured
  transcript ends at 15:49 (949 s). Window 1 (0–600 s): ok, 27 s, $0.049. Window 2 (600–960 s)
  timed out at 90 s, was retried by `_MediaCall.run` (timeout counts as transient), and the retry
  was cancelled by the 150 s run limit. Page-style retry (window 2 only): same, timeout + cancel.
  Item spend $0.193 (two ok-less estimates per attempt, $0.036 each), no transcript; the next
  attempt would hit the 2× ceiling ($0.192). Harness spend so far $0.19.
- Suspect (unproven): window 2's `end_offset` is 11 s past the real end. Design gap either way:
  a timed-out window is retried inside a run that cannot fit the retry.
- Not run yet: analyse, second reader, personas, card, refusals. Extra test videos (Hindi, two
  short English) need a read of production `rec_cache`; that read was blocked by the permission
  classifier. Driver: `scripts/harness_media.py`; one-call probe: `scripts/probe_media.py`.
- Sourabh: "yes do what u feel is correct". Probe of window 600–949 (ending at the real end, one
  attempt): timeout at 91 s, $0.035, so ending past the end was not the cause. Production
  `rec_cache` read blocked again by the classifier; not retried.
- Plan Round 4 (one whole-URL call per video, 20-min cap, no in-run timeout retry, 504 on
  timeout, max tokens 16,000) → plan-reviewer REVISE 6, REVISE 2, APPROVE. T04 frozen in
  `7622bb7`; code in `88e932f`; API suite 934 passed, ruff clean.
- **Re-run on a fresh emulator: the whole 16-min video in one call also timed out at 90 s**
  ($0.096, one charge, no retry, 504 as designed). So offsets were not the cause: tonight every
  call that reaches past minute 10 of this video hangs, while 0–600 answered in 27 s and
  yesterday's whole-video call (row 3, default thinking) answered in 29 s. Round 4's premise is
  unproven; its timeout handling stands on its own.
- Real Vertex spend tonight $0.325, all in emulator ledgers (a fresh emulator re-seeds only
  production's spend, so the harness allowance resets each restart; capped by hand at $1).
- Stopped for Sourabh. Next (his call): one call in row 3's exact shape (default thinking,
  ~$0.08) to test low thinking as the cause, then a second video (T04) if it still hangs; or
  park video transcripts and move to step 4 / M9.
- Sourabh: "go ahead and do it today". Probes (one attempt each, 180 s limit, emulator ledger):
  whole 16-min video at **default** thinking → timeout 181 s ($0.095); T04 whole (18.6 min, low)
  → timeout 181 s ($0.112); **first 3 min of the 16-min video → timeout 181 s ($0.018)**. Text
  smoke on the same model: ok, 5 s, $0.001. So since about 18:23 UTC every YouTube-URL call
  hangs, at any length, with or without offsets, at any thinking level; 0–600 answered in 27 s
  just before. Cause is on Vertex's YouTube fetch, not our code (Google AI forum has reports of
  YouTube-URL input on Vertex failing intermittently with 400 / 504 / timeouts).
- Real Vertex spend tonight ≈ $0.55 (first emulator $0.229, second $0.322), emulator ledgers only.
- T04's decision rule could not be measured; Round 4's 20-min cap and single call stay as
  committed but unverified. Next: a $0.02 re-probe (first 3 min) later today; when it answers,
  re-run acceptance 1–3 and T04. Until then, step 4 (web) needs no Vertex.
- Re-probe at 19:03 UTC (first 3 min, low, offsets, 180 s limit, bare Firestore emulator
  ledger): **OK in 27 s, $0.015**, 8 paragraphs, 375 words, starts 2..177, en. Vertex's YouTube
  fetch answers again. Acceptance 1–3 and T04 not re-run yet (asked Sourabh: now, or step 4 first).

## Media build, step 4 (2026-10-14, web; code done, shots after the step 3 re-run)

- Sourabh: "go to four then check after that": step 4 first, then step 3's acceptance 1–3 and T04.
- **Annotator 0.9.0**: `labels: {author?, card?}` option; `data-rl-ui="host"` marks a control
  the host owns: anchors and copy skip it, `destroy` leaves it (React StrictMode mounts, destroys
  and re-mounts the annotator in dev, which would otherwise strip the time buttons). Extension
  untouched (still 0.8.0, not rebuilt). Test: `test/host.test.ts`.
- **Web**: lazy `components/reader/MediaReader.tsx` (one chunk, two exports): `MediaReader`
  (click-to-load no-cookie player, seeking over postMessage with a strict origin and source check,
  spoken paragraph marked with `data-rl-now`, Follow along toggle paused 5 s by wheel / touch /
  scroll keys, transcribe loop: 202 → 5 s, 504 retried once then "Try again" + "Open original",
  422 / 410 → the API's message + "Open original") and `TranscriptBody` (a time button per
  paragraph). `lib/media.ts` pure, chunk-only. ReaderPage: kicker "Video · 16 min · channel",
  transcript note under the dek, stored `refused` / `failed` stop with "Open original" (also an
  article's `failed`), "Before you watch", speaker labels on cards, the annotator waits for the
  lazy body. Entry points use `open_here` (feed, Up next "Open here" + "Watch on YouTube"); Read
  any link says "article or YouTube link" (podcast wording waits for step 6, so a cut of podcasts
  needs no copy change); library rows get a Video / Podcast badge; privacy page: Videos section and
  "videos opened" in daily counters.
- Choices to flag at review: `allow` adds `autoplay` (the click must start playback) and
  `fullscreen`; the disclaimer line wording is mine ("A transcript made automatically from the
  video. It can differ from what's said; the recording is the source."); the spoken-paragraph
  mark uses wash + ink rule, not the accent (the accent only means a note).
- Bundle: main **149.46 KB** gzip (148.31 at `8bf7797`; budget 150, 0.54 KB left). The transcribe
  loop moved into the media chunk to get there (149.80 before). Media chunk 2.82 KB JS + 0.85 KB
  CSS. Step 6 must keep main-bundle changes near zero.
- Tests: annotator 60, web 164 (+16, `test/media.test.tsx`: helpers, player messaging, ReaderPage
  transcribing → transcript → notes, timeout retry, refusals), extension 85, API 934; typecheck clean.

- Step 3 re-run, 19:21 UTC, fresh emulator (seeded production $0.6543, harness budget $1.6543):
  open 200 free; **whole 16-min video transcribe → 504 after 91.5 s, $0.096** (one charge, no
  in-run retry, as designed). The 3-min probe at 19:03 answered in 27 s. So short clips answer and
  the whole video still hangs; tonight's spend so far $0.111. Stopped for Sourabh.
- Sourabh: "test". T04 (`rrkrvAUbU9Y`, 18.6 min, a different video), 19:27 UTC, one whole-URL
  call: **504 after 90.1 s, $0.112**. So it is not the 16-min video: whole-video YouTube-URL calls
  on Vertex time out tonight while a 3-min clip answers. T04's decision rule still unmeasured.
  Tonight's spend $0.223, emulator ledgers only. Stopped for Sourabh (park video transcripts or not).
- Sourabh: "yes do what u feel is correct" → **video transcripts parked**. Step 4's web code stays.
  Nothing is deployed, so no switch is flipped now. Only `MEDIA_ENABLED` (all media) and
  `MEDIA_AUDIO_ENABLED` (podcasts) exist; shipping podcasts with videos off needs a
  `MEDIA_VIDEO_ENABLED` switch (open → `media_off`, `open_here` false for videos). It goes into
  step 6's plan round, not tonight. Before deploy: a $0.02 short-clip probe plus one whole-video
  call; if the whole video still times out, deploy with videos off.

### Next steps (resume here, in order)
1. Midday check-in with Sourabh (asked 2026-10-14 ~01:00 IST): step 4 done, videos parked, spend
   tonight $0.223 (emulator ledgers), production today $0.6543. Whether to start podcasts (step 6).
2. Step 6 plan round (podcasts + `MEDIA_VIDEO_ENABLED`) → plan-reviewer → build → harness run on the
   22-min episode. Acceptance 4 shots then use the podcast; video shots wait for a working probe.
3. Before deploy: re-probe video (short clip, then one whole video); off unless both answer.
4. Checkpoint end of Oct 14 IST: not merged → ask Sourabh what to cut (decision 27).

## Media build, step 6 (2026-10-14, podcasts; plan round)

- Check-in answered, ~01:10 IST. Sourabh: "start podcast plan".
- Plan Round 5 written into `docs/plans/media.md`: Apple episode links only (direct `.mp3` links
  cut), `MEDIA_VIDEO_ENABLED` switch (never remembered as a refusal), MP3 pieces cut on time only
  so piece i = window i, a fingerprint so a retry with different dynamic ads starts over, web
  audio player in the media chunk, harness on T02 (expected ≤ $0.35, emulator ledger).
  Sent to plan-reviewer.
- plan-reviewer: REVISE 12 (big ID3 tags, hosts ignoring Range, one source for pieces and
  windows, piece ≤ 14.5 MB, transient fetch errors not remembered, semaphore released on every
  exit, `media_off` never remembered and `apple_link_only` for `.mp3` links, web flag read from
  `deploy.env.yaml`, video switch checked by API only, memory units, Apple field caps, tests) →
  all applied → **APPROVE**, two nits applied.

### Next steps (resume here, in order)
1. Build step 6 per Round 5 + its review: `mp3.py` → `audio_head` / `fetch_audio` → Apple lookup →
   switches + service audio branch → web `AudioPlayer` → suites.
2. Harness on T02 (5.7, ≤ $0.35, emulator ledger; state the cost before running) → shots → log.
3. Step 7. Checkpoint end of Oct 14 IST (decision 27).

## Media build, step 6 (2026-10-14, podcasts; build)

- Resumed after /clear: "resume at building step 6, starting with the MP3 splitter".
- `app/media/mp3.py` (pure) + `tests/test_mp3.py` (46 tests, written first, red then green):
  Layer III headers (MPEG 1, 2, 2.5), ID3v2 (footer flag), ID3v1 and APEv2 skipped and left out
  of the 90% share (5R1), resync confirmed by the next header, cut-off last frame dropped,
  < 30 s or < 90% frames → `unsupported_audio`. Frame times are integer samples / rate per run,
  so a 660.0 s file floors to 660, not 659. `split` cuts at the first frame ≥ each window start,
  raises `ValueError` unless the windows are `plan_windows(floor(walk.duration_s))`, refuses a
  piece over `MAX_PIECE_BYTES = 14_500_000` (5R3, 5R4); pieces are memoryviews. Tails 59.4 /
  59.6 / 60.0 / 60.4 s pinned. `id3v2_size` and `first_frame` ready for `audio_head`.
- Signature note: `split(walk, windows)` takes the `Walk` (which holds the bytes) instead of
  5R3's `split(data, windows)`, so the bytes are walked once; same rule, same assertion.
- Local timing: a 65 MB, 45-min 192 kbps stream walks in 0.03 s; pieces 4 × 14.4 MB + 7.2 MB.
- API suite 980 passed, 2 skipped; ruff clean.

- `SafeFetcher.audio_head(url, start=0, length=64 KB)` and `fetch_audio(url, max_bytes,
  expected_bytes)` + `tests/test_safe_fetch_audio.py` (39 tests, written first). Same per-hop
  validation, pinned connect and robots rule as pages; 6 redirects; `Accept: audio/mpeg,*/*;q=0.1`;
  type `audio/mpeg` / `audio/mp3` else the guard's `not_html`. Head: `Range` GET, total from
  `Content-Range` on 206 or `Content-Length` on 200; a host ignoring Range is read to 64 KB and
  closed (5R2, pinned: < 1 MB of a 50 MB body pulled); `start` serves 5R1's second probe (skips
  on a 200; a 206 for another range is an error). Fetch: 45 s, one bytearray preallocated from
  the head's total, cut off past `max_bytes`, error bodies never read (5R10).
  `is_transient(FetchError)`: timeout, connection error, 5xx, 429 (5R5). `_get` gained
  `max_redirects` / `timeout_s` / `headers` / `read`; page fetches unchanged (old tests pass).
- Split of duties: `safe_fetch` stays HTTP-only. The ID3 second probe, `mp3.first_frame`, size
  caps and FetchError → `unsupported_audio` / `MediaUnavailable("audio")` go in `sources.py`
  beside the Apple lookup (next).
- API suite 1019 passed, 2 skipped; ruff clean.

- `sources.apple_episode(show, episode, settings)` + `probe_audio(url, settings, fetcher)` +
  `estimated_duration_s` (30 tests added to `test_media_sources.py`, written first). Lookup
  `itunes.apple.com/lookup?id=<show>&entity=podcastEpisode&limit=200`; show page →
  `not_an_episode` with no request; `trackId` matched as int; `episodeUrl` https ≤ 2,048 else
  `episode_not_found`; extension other than mp3 → `unsupported_audio`, missing falls through;
  length 0 = unknown, < 30 s `no_speech`, over cap `too_long`; non-Latin title `not_english`;
  title ≤ 300, show ≤ 120, artwork https only; HTTP / network / garbage → `MediaUnavailable`.
  Probe: head through the guard; no total → `unsupported_audio`, over bytes cap → `too_long`;
  ID3 past the head → 16 KB second probe at the tag's end (5R1, tested with a 1 MB tag, with and
  without Range); no frame → `unsupported_audio`; transient FetchError → `MediaUnavailable`,
  other → `unsupported_audio` (5R5). Logs carry codes and statuses only, never the URL.
- API suite 1049 passed, 2 skipped; ruff clean.

- Resumed after /clear: "resume at step 6: switches, then the service audio branch".
- Switches (5.1, 5.2, 5R7): `MEDIA_VIDEO_ENABLED` (default true, in `deploy.env.yaml`);
  `openable.media_kind_on(kind, settings)` = kill switch and the kind's switch, checked first in
  `open_media`, in `openable` and at the top of `transcribe_pending` before the lease. New code
  `apple_link_only` for direct `.mp3` links (in `MESSAGES`). `refusals.NOT_REMEMBERED` =
  {`media_off`, `apple_link_only`}: `remember_refusal` skips them and the transcribe `refused`
  mark leaves them out, so the old `youtube_info` missing-key path can't remember one either.
  Show pages answer `not_an_episode` before the slot and any lookup, not remembered (URL-derived).
- `openable`: an Apple episode is "Open here" when the audio switch is on and its length is
  unknown or ≤ `MEDIA_MAX_AUDIO_S`; YouTube follows the video switch; `.mp3`, show pages,
  Spotify stay "Open original".
- `open_media` audio branch: Apple lookup and the audio probe each count one `media_lookup`;
  no Apple length → bitrate estimate, over the cap `too_long` (remembered); then budget
  pre-check, growth slots, `create_media` as for YouTube. `Media(kind="audio",
  audio_url=episodeUrl, language=None)`, `url` = the canonical Apple link.
- `transcribe_pending` (5R6): cached → switch → refused → stage → audio slot
  (`Semaphore(1)`, `locked()` then `acquire()`, busy → `TranscribeBusy` / 202) → budget → lease
  → run, one `try/finally` from the slot on. Free exit widened to `(BudgetExceeded,
  MediaUnavailable)` with nothing billed (nit 2). Router: `MediaUnavailable` → 503
  `media_unavailable`, Retry-After 60.
- `_Run` audio: fetch through `get_fetcher().fetch_audio` (transient → `MediaUnavailable`, not
  remembered; other → refused and remembered), walk, the walk's floor length replaces the
  lookup's for windows, ceiling and stored media (over the cap `too_long` before any call),
  `split(walk, plan_windows(...))`, `AudioClip(piece)`, `check_window(relative_only=True)`,
  `MEDIA_AUDIO_PARALLEL_WINDOWS` (new, 4) after window 1 alone. Fingerprint written with every
  audio `save_window`; a retry whose walk differs calls `drop_windows` (lease-checked, cost kept)
  before any model call. Audio runs log fetch / walk / windows ms and `peak_rss_mb` (ru_maxrss
  normalised for macOS / Linux).
- Two small departures from the plan text, both deliberate: a fetch cut off as `too_large` at
  transcribe answers `too_long` (the plan's 5R5 list said `unsupported_audio`; the head already
  answers `too_long` for the same cause, and the message is the accurate one). And `_read_into`
  presizes from the response's Content-Length when no head total is passed, since the transcribe
  run doesn't carry the open's probe (5R10's intent, no new stored field).
- Tests: `test_media_podcast.py` (21, new): open → transcribe → analyse with relative piece
  times made absolute and `audio_url` reaching `contents/`; window 1 alone; estimate at open;
  `.mp3` and show page before any lookup; `media_off` per switch never remembered, then on again
  works at once; video switch leaves podcasts alone; `remember_refusal` skips switch codes;
  transient vs permanent at open and transcribe; walk over cap; ceiling from the walk; non-English
  after window 1; busy slot leaves lease and both counters; slot free after budget and refused
  runs (and asserted after every test); same bytes keep saved windows, different bytes drop them.
  Plus openable (switches, Apple with / without length, show page, `.mp3`), router (podcast 422s,
  transcribe 503) and a presize test. Written alongside the code this time, not strictly first.
- API suite 1083 passed, 2 skipped; ruff clean.

- Web (5.5, 5R8): `AudioPlayer` in the `MediaReader` chunk: `<audio controls preload="none">`
  from `audio_url`, no referrer attribute (R10), `timeupdate` marks the spoken paragraph, a time
  button sets `currentTime` and plays, `error` → "This episode's audio couldn't be played here."
  with Open original (the transcript stays). The shared behaviour (time-button delegation,
  marking, Follow and its 5 s pause) moved out of `VideoPlayer` into one hook both players use;
  the video tests pass unchanged. Bar link reads "Open in Apple Podcasts". Read any link copy
  follows `VITE_MEDIA_VIDEO` (default on). `make deploy-web` reads `MEDIA_VIDEO_ENABLED` from
  `apps/api/deploy.env.yaml` with `sed -E` (the BRE `\|` form printed nothing on macOS; caught
  before use) and fails if it is missing. Privacy page gains "Podcasts" with R10's wording.
- Tests: audio no preload / no YouTube / no referrer attribute; seek + play; `timeupdate` marks;
  error state; podcast ReaderPage (kicker "Podcast · 22 min · …", audio usable while
  transcribing, transcript after); placeholder and hint under both flag values. Web 171 passed,
  typecheck clean, main bundle 149.47 KB (was 149.46; budget 150), media chunk 3.12 KB.

- Harness on T02 (5.7 item 1-2; `harness_media podcast`, the video `main` now takes a case with
  the frozen thresholds). Stated before running: ≤ $0.35. Emulator ledger, real Vertex:
  open 4.3 s ($0); transcribe 55.3 s, 3 windows, **$0.1100** (≤ $0.14); analyse 22.0 s, $0.011;
  explain $0.0079. **Run total $0.1289.** Transcript 55 paragraphs, **4,085 words** (≥ 3,600; the
  fast model's whole-file reference was 4,081), last start 1,310 s (≥ 1,260), non-decreasing,
  inside 1,347 s. Second reader: no model call, no slot. Personas newcomer 3 / trader 4 notes.
  "windfall tax" → `verified`. Server phases: fetch 7.1 s, walk 53 ms, windows 48.2 s.
- **Miss: peak RSS 686 MB (target ≤ 600).** An idle API on the same emulator is 277 MB, so the
  run added ~410 MB for a 32 MB file with two windows in flight (window 1 alone, then 2 and 3).
  5R10's first remedy applied: `MEDIA_AUDIO_PARALLEL_WINDOWS` 4 → 2 (config default and
  `deploy.env.yaml`). It does not change this run (only two were in flight) but caps a 45-min
  episode at two instead of four. 5R10's second remedy (lower `MEDIA_MAX_AUDIO_BYTES`) would
  refuse T02 itself at anything under 32 MB, so it waits for Sourabh. API suite 1083 passed.

- **Decision (Sourabh, 2026-10-14 ~11:20 IST): "Audio and Video is just minor additional
  support, don't make them good enough; small 10 minutes clips are good enough."** Applied:
  `MEDIA_MAX_VIDEO_S` and `MEDIA_MAX_AUDIO_S` 600 (were 1200 / 2700), `MEDIA_MAX_AUDIO_BYTES`
  20 MB (was 70), config defaults and `deploy.env.yaml`; `too_long` message "up to 10 minutes for
  now". One window per recording, so the memory question closes without work (T02's 686 MB was
  a 32 MB file; a 10-min file is ≤ 20 MB with nothing in parallel). The multi-window code stays;
  its tests pin the old caps (`LONG_CAPS`) and a new test pins the 10-minute defaults. T01 and
  T02 stay frozen as written and are now over the default cap (a harness run on them needs the
  caps raised in its env). Cut from 5.7: items 3-5 (refusal sweep, pre-check count, podcast
  shots) and the copy-hunt investigation. API suite 1084 passed.

## Media build, step 7 (2026-10-14, the video deploy decision)

- Video re-probe (`scripts.probe_media`, fresh emulator, harness budget $1.00, production spend
  today $0), 05:55 UTC. Production route settings (quality model, low thinking, 90 s timeout).
  - Short clip, T01 0:00-3:00 with offsets: **OK 10.4 s, $0.0153**, 382 words.
  - Whole video, no offsets, under the new 10-min cap: Kurzgesagt "The Egg" (`h6fcK_fRYaI`,
    486 s; picked by me, Sourabh had none; lookup passes every `youtube_info` check):
    **OK 50.6 s, $0.0467**, 900 words, last start 7:15. The first answer failed a
    `check_window` check and the in-call re-ask passed (reason not captured: my output filter
    dropped it). Second run, full log kept: **OK 45.4 s, $0.0264, first try**, 898 words,
    last start 7:20.
  - Session probe spend $0.0884, emulator ledger only.
- **Decision: video ships on** (`MEDIA_VIDEO_ENABLED: "true"` stays; the web flag follows).
  The whole-URL hang was on 16-19 min videos; under the 10-min cap one call answers in
  45-51 s, inside the 90 s timeout. Watch item: one first-try check failure in two runs.

- `scripts/ingest_media.py` built (3a8f93f): `open_media(media, None, ...)` = no reader (no
  daily slot, no growth slots), `look_up(..., day=None)` for a dry run that counts and writes
  nothing, ≤ 6 per run, target database printed first. 7 tests. Dry run on the emulator: "The
  Egg" one window 0-486 s, est. $0.049; T02 `too_long`. Real run on the emulator: stored, 899
  words, 24.7 s with analysis, media spend $0.042.
- Docs (9137c26): DESIGN §21 plus pointers in §3, §4, §8, §10, §11.2, §11.4, §11.5, §16.6,
  §17.4; CLAUDE.md layout and the `transcribe` cost line; stale config comment fixed.
- Video reader check (`tools/shots/media.py`, cut-down acceptance 4): 0 failed checks, axe 0 at
  every impact, 24/24 paragraphs match, "Play from 1:30" → player at 90 s. "The Egg" has 0
  notes for the newcomer (outside the graph's domains): live check and seeding need an
  economics or news video.
- STATUS (ab0c6d6): header, milestone row, 6 deviations, 4 known issues (Vertex YouTube fetch
  intermittent: the fallback is `MEDIA_VIDEO_ENABLED=false`), costs, §24. Suites: API 1091,
  web 171, annotator 60, extension 85, typecheck clean, main 149.47 KB.

- Live-check picks, dry-run then rehearsed on the emulator: The Economist "How does raising
  interest rates control inflation?" (`R8VBRCs2jTU`, 494 s) and The Indicator "How the rich make
  money by losing money" (Apple `id1320118593?i=1000791671873`). The episode, listed 565 s,
  downloads at 652 s (stitched-in ads) and was refused `too_long` at no cost.
  **Sourabh: "raise to 12"** → `MEDIA_MAX_AUDIO_S` 720, bytes 24 MB, message "videos up to 10
  minutes, podcasts up to 12" (efba893). Then 1,755 words, $0.054.
- **Bug found and fixed:** both economics recordings showed 0 notes: `ingest_media.py` ran
  analysis with the empty default graph (only API startup loads it), so no demand linked.
  `load_serving_graph` now shared by startup and the script; the script refuses without a graph.
  Re-seeded T05: 8 notes for the newcomer.
- milestone-reviewer round 1: **FIX** (4 blocking, 8 more). All blocking and items 5-10 applied
  (b6b01b2 .. c41fc8a): ad-padded episode test, privacy copy, filler-words note, STATUS §5/6/8/9,
  known-length rule for "Open here", no transcript text in invalid-output logs, DESIGN §8, T05
  and T06 frozen. API 1,095, web 171, main 149.48 KB.

- Round 2: **SHIP**. Shots retaken with the final note text (the script now paces page loads
  under the demo's 60 requests a minute). PR #32, CI green, squash-merged (5844e98). Local
  `main` reset to `origin/main` (its one unpushed commit, the plan docs, is inside the merge).
- **Deployed:** API revision `readlayer-api-00027-q2s` (health ok), then web
  (`VITE_MEDIA_VIDEO=true`, main 149.48 KB), on Sourabh's yes at each prompt.
- **Live, Sourabh (Google reader):** a Fireship video (5:56) opened in Gloss: transcript and 2
  notes, "loved it". The player showed YouTube's "Sign in to confirm you're not a bot".
  Embed test (local page, iframe like Gloss, T05): headless signed out → both `youtube-nocookie`
  and `youtube.com` show the check; Sourabh's signed-in Chrome → no-cookie shows it,
  **`youtube.com` plays**. Sourabh: switch to it.
- **Sourabh:** feed videos should offer Gloss or YouTube; "keep long ones as YouTube only".
- Plan `docs/plans/media-followup.md` (web only, branch `media-followup`) → plan-reviewer.

## Media follow-up (2026-10-14)

- plan-reviewer: REVISE 7 (bundle: ForYouTab is lazy, so a Row `actions` slot; accessible
  names and disabled while opening; player tests on literal origins; feed tests; a fixture-driven
  For you shot; docs and decision 55; privacy wording) → applied as plan Round 1 → **APPROVE**.
- Built (tests first): afa20cd player on `www.youtube.com` + privacy page (and test);
  9607228 `lib/recLabels.ts`, Row `actions` slot, `MediaChoice` in ForYouTab, Up next names the
  original. Web 180, typecheck clean, main **149.61 KB** (149.48), ForYouTab 2.29 KB (2.09).
- Shots (78fd5de): `tools/shots/media_followup.py` (For you from a fixture, 1440/390 light and
  dark: axe 0, no scroll, rows right, Tab reaches both controls with a ring) and `media.py`
  (player origin `https://www.youtube.com`): 0 failed checks. Docs: DESIGN §21.4, decision 55,
  STATUS §1/§4/§5/§25, Media marked merged and live.
- milestone-reviewer round 1: **FIX** (stale STATUS §9 and this resume point; plus a second open
  from the title while busy, duplicate shots, missing suite counts). All applied.

### Next steps (resume here, in order)
1. milestone-reviewer round 2 → SHIP → PR → CI green → merge → `make deploy-web` (Sourabh's yes).
2. Live: Sourabh plays a video in Gloss signed in to YouTube and opens a feed video both ways;
   T05 and T06 live, then a demo reader (free). Checkpoint end of Oct 14 IST (decision 27).
