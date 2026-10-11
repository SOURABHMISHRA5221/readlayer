# ReadLayer — project status and handoff

Last updated: 2026-10-11 (IST): Design pass (Gloss) merged (#22, #23) and live (API revision
00019, web deployed); live check passed after the CORS fix for Save (§18). Next: M8-local (rebase
`m8` first). M7.5 merged (#20) and live,
Sourabh's Google check done.
M2.2 merged (#18) and live (§16; frozen-graph headline missed, decision 36). M8 paused. M7 live (#16, §15); M6 live (#14, #15, §14). Autopilot run log in `docs/AUTOPILOT_LOG.md`.
Read this together with `CLAUDE.md` (rules), `docs/DESIGN.md` (spec) and `docs/BUILD_PLAN.md`
(milestone prompts). Where this file and DESIGN.md disagree, the "Deviations" section explains
why; DESIGN.md is still the target unless a deviation says otherwise.

Hackathon: Google Cloud AI Builder Cup. **Team lock Oct 11. Deadline Oct 18; we submit Oct 17.**

---

## 1. Milestones

| Milestone | State | PR | What it delivered |
|---|---|---|---|
| Bootstrap | merged | — | Project kit, Firebase default project, CLAUDE.md precedence note |
| M0 | merged | #1 | Monorepo scaffold, `app/llm.py` (LiteLLM, routes, fallbacks, budget guard), CI, Dockerfile, Makefile, skeleton Cloud Run + Hosting deploy |
| M0.1 | merged | #2 | Tighter LLM fallback rules (`classify_error`: retry/fallback/reject) |
| M1 | merged | #3 | `safe_fetch` SSRF guard, trafilatura extraction, features, demand extraction, POST /v1/content |
| M2 | merged | #4 | 290-article corpus ingested, concept graph build (`build_concepts`), entity linking, `link_confirm` on MODEL_QUALITY |
| M2.1 | merged | #5 | Graph grown to 3,327 concepts, overrides file, held-out linker evaluation (15 articles) |
| docs | merged | #7 | Reading profile page spec (DESIGN §15) |
| docs | merged | #8 | DESIGN §2 brought up to date with the M2.1 build |
| M2.2 | merged (squash), **live** | #18 | 14-domain taxonomy, kind/jurisdiction, overrides (Russell, Tax alias, Chancellor, FTSE Russell), jurisdiction-aware linker (link_confirm v3), glossary-seeded graph live (5,206 concepts after the fold), online growth **on** (any reader within the caps), Delete-button fix. Frozen-graph headline missed (64% / 13%), shipped under decision 36. See §16 |
| M6 slice + redesign + M6.5 | merged (squash) | #9 | See below. One commit on `main`: `M6-slice: vertical slice, redesign, recommendations` |
| M3 | merged (squash) | #10 | Reader model, auth, rate limits, events, export/delete, reading-profile API, rec state + ingest counter in Firestore, first full deploy. See §11 |
| M4 | merged (squash) | #11 | Real gap scorer, seeded personas, closed loop, deploy guard. See §12 |
| docs | merged (squash) | #12 | README with live screenshots, persona GIF, diagrams; MIT license |
| M5 | merged (squash) | #13 | Verified personalised explanations, safety evals, card UI; live (Oct 10). See §13 |
| Rest of M6 | merged (squash) | #14 | Paragraph markers, pre-read, "Know this?", full event batching, two-phase "Open here", shared restatement; live (Oct 10). See §14 |
| M7 | merged (squash), live | #16 | Consent, onboarding, calibration, profile page with knowledge map, edit-by-prompt (demo: session-only), emulator harness. See §15 |
| M7.5 | **merged #20 and live** (§17); Sourabh's Google check done (2026-10-11) | — | "For you" feed, "Read any link", reading goals, general explanation prompts (decisions 33, 37, 38) |
| Design pass | **merged #22 + #23 and live** (§18) | — | Gloss: tokens and type, Margo, library as a feed, reader, profile and SVG map (decisions 39, 40) |
| Landing and onboarding | planning (decision 41) | — | Landing page with live mini-demo; onboarding in 2 screens with web results |
| M8-local | plan approved; redaction + NOT_CORPUS built; **paused** on branch `m8` | — | Unpacked extension, after M7.5 |
| M9 | not started | — | Hardening and evals |

**PR #9 (`m6-slice`, squash-merged) had four parts, all local-only (nothing deployed):**
1. `e7c131c` M6 local vertical slice: `DEV_AUTH_BYPASS` (refuses to start on Cloud Run / ENV=prod),
   GET /v1/content (list + search), GET /v1/content/{id}, GET /v1/content/{id}/annotations with a
   PLACEHOLDER scorer (`app/scoring/placeholder.py`, DESIGN §5–6 math, prior-only, demo personas),
   the real `packages/annotator` (anchor resolution, marks, ARIA card), library + reader pages,
   `make dev`.
2. `b4e0f90` Redesign: design tokens (light/dark + toggle), Newsreader + Inter with metric-matched
   fallbacks, annotator card on Floating UI with bottom sheet and focus trap, diffed persona
   switch animation, margin rail / drawer, end-of-article block, library front page with
   images and per-persona "N concepts new to you", publisher metadata backfill
   (description, author, published, og:image). Lighthouse: reader a11y 100, CLS 0.
3. `807e263` M6.5 "Up next and explore": web search (Tavily, YouTube), corpus recommendations,
   ranking, GET /v1/content/{id}/recommendations, POST /v1/recs/events, POST /v1/recs/open
   ("Open here"), Up next UI with Read / Watch / Listen.
4. Handoff: format mix 3/2/1, `user_ingested` source, image fallback on Up next thumbnails,
   `deploy.env.yaml` LINK_THRESHOLD 0.865, DESIGN §3/§8/§16, BUILD_PLAN M3 update, this file.

---

## 2. Architecture as built

| Piece | Where it runs | State |
|---|---|---|
| `apps/api` FastAPI, Python 3.12 | Local `make dev` on :8000. Cloud Run `readlayer-api`, asia-south1, min 0 / max 3, 1 vCPU / 1 GiB | **Live, M7 build**: revision `readlayer-api-00012-ccv`, https://readlayer-api-d2sfihz3za-el.a.run.app (also https://readlayer-api-751104670850.asia-south1.run.app) |
| `apps/web` Vite + React + Firebase Auth | Local `make dev` on :5173, proxies `/v1` to :8000. Firebase Hosting | **Live, M7 build** (bundle `index-Dm3tU99c.js`): https://readlayer-sourabh-26.web.app (Firebase web app `readlayer-web`) |
| Firebase Auth | Google + Anonymous providers | Live. Anonymous = demo mode with personas |
| `packages/annotator` | Bundled into the web app (and the extension in M8-local) | 0.4.0 (M6): two-part card, paragraph markers, "Know this?" chip, pre-read, reading signals |
| `apps/extension` | — | MV3 scaffold only (M8-local: unpacked, activeTab only, Oct 14) |
| Vertex AI (Gemini, Gemma MaaS, embeddings) | `global` endpoint, project `readlayer-sourabh-26` | Live, via ADC locally |
| Firestore (Native) | asia-south1 | Live |
| Cloud Storage | `gs://readlayer-sourabh-26-graph/concepts.json` (+ `concepts.prev.json`) | Live, loaded at API start |
| Secret Manager | `uid-hash-salt`, `tavily-api-key`, `youtube-api-key` (asia-south1, runtime SA has accessor) | Live |
| Tavily, YouTube Data API v3 | External, called only from the API | Keys from Secret Manager on Cloud Run; local `.env` locally |
| Firestore rules | `firestore.rules` deny all client access | Deployed |
| Firestore TTL | collection groups `events` (90 days) and `pending_contents` (24 h, M6), field `expire_at` | Enabled |

**LLM routes** (`app/llm.py` `ROUTES`; model ids come from env, never code):

| Task | Primary | Fallback | Notes |
|---|---|---|---|
| extract_demands, link_merge, concept_define, concept_prereqs, concept_wikidata, smoke | MODEL_FAST `vertex_ai/gemini-3.5-flash-lite` | MODEL_FALLBACK `vertex_ai/google/gemma-4-26b-a4b-it-maas` | |
| link_confirm | MODEL_QUALITY `vertex_ai/gemini-3.8-flash` | MODEL_FAST | 45 s timeout, batches of 10 |
| restate | MODEL_QUALITY | MODEL_FAST | M6: "What the author is saying", once per (span, style), shared |
| explain | MODEL_QUALITY | MODEL_FAST | M6: Background only, per reader; regenerate once with reasons |
| verify | MODEL_JUDGE (empty = MODEL_QUALITY) | none | claims judge for the restatement; outage → definition card, nothing cached |
| verify_background | MODEL_JUDGE (empty = MODEL_QUALITY) | none | M6: Background judge (contradiction, article claims) |
| profile_edit | MODEL_FAST | MODEL_FALLBACK | M7: edit profile with a prompt (flat schema, strict local whitelist); prompt `profile-edit-v3` |
| embed | MODEL_EMBED `vertex_ai/gemini-embedding-001`, 256 dims | none | |

No LLM call on the annotations, library or recommendations paths. POST /v1/explain (M5) is the
only reader-facing path that may call a model, and only on a cache miss within the daily caps.
"Open here" runs the normal ingestion pipeline in two requests (M6): phase 1 fetch + extract
(no LLM), phase 2 extract_demands + linking (POST /v1/content/{id}/analyse).

**Firestore collections in use:** `contents/{url_hash}` (shared demand profiles),
`pending_contents/{url_hash}` (fetched, not yet analysed; no user data; TTL on `expire_at`,
24 h, active since the M6 deploy),
`explanations/{key}` (two entries per card since M6: shared restatement, per-reader Background), `explanation_reports/{id}` (review queue, no user id),
`ops/explain/days/{date}` (hits, generated, outcomes, shared anonymous generation count),
`ops/spend/days/{date}` (LLM ledger), `ops/search/days/{date}` (search-call ledger, now with an
`anonymous` counter), `ops/ingest/days/{date}` (shared anonymous ingest count),
`rec_cache/{concept_id}__{format}` (web results, concept-level, 48 h), and per reader
`users/{uid}` with `domains`, `knows`, `events` (TTL), `weekly`, `profile_edits` (M7),
`rec_signals/{persona|default}`, `ingest_counts/{day}`, `explain_counts/{day}` (M5),
`profile_edits/{id}` and `profile_edit_counts/{day}` (M7), plus `consent`, `field`, `onboarding`
and `calibration` fields on `users/{uid}` (M7); `ops/profile_edit/days/{day}` (shared anonymous
profile-edit count). All per-user data is in
`reader_repo.USER_SUBCOLLECTIONS`, which drives both export and delete.

---

## 3. Data state (2026-10-04)

| Item | Value |
|---|---|
| Content docs in Firestore | 312 total (309 + 3 "Open here" tests: M6 local, M6 live, M6 warm-timing live) |
| Corpus (in `data/corpus_urls.txt`) | 290 |
| Held-out (in `data/heldout_urls.txt`) | 15, never used to build the graph |
| `user_ingested` ("Open here" testing) | 4: chain.link "Singleness of money", ECB macroprudential explainer, Wikipedia "Yield curve control" (M6 local), Wikipedia "Quantitative tightening" (M6 live) |
| Other | 2 M1 acceptance URLs (BusinessLine RoDTEP, JGU PLI evaluation), source `fetch`, in neither list |
| Publisher metadata backfilled | 306/306 dates, 273 authors, 236 standfirsts, 271 images (before the 3 docs added later) |
| Concept graph | version `2026-10-04` (+ `doc_freq` on 3,325 concepts, uploaded 2026-10-05), 3,327 concepts (finance 1,279, economics 1,064, policy 557, business 427), 4,053 prerequisite edges, 680 Wikidata ids, acyclic |
| Held-out linking (M2.1) | 186 concept/term demands: 57% exact-name, 5% model-confirmed, **62% linked**, 38% unlinked. LINK_THRESHOLD 0.865 |
| Held-out set (M2.2, 2026-10-10) | 30 URLs (15 business + 15 non-business, domain column fixed before measuring); the new 15's demands frozen (`data/heldout_new_demands.json` + sha256), not yet stored in Firestore |
| Held-out linking (M2.2, local, seeded graph) | frozen graph: business 64%, non-business 13%; after growth (production behaviour): 89% / 66%. `apps/api/evals/heldout_report.md` |
| Concept graph (live, 2026-10-10) | `2026-10-10-folded-5206`: 5,201 seeded + 5 grown concepts, 14 domains, kind + jurisdiction on all. GCS `concepts.prev.json` is the seeded file; the pre-M2.2 graph is only in local `data/concepts.json` (rollback to a pre-M2.2 revision: upload that file first) |
| Content docs (M2.2) | +15 held-out docs (source `fetch`), +1 live-check doc; 49 docs re-linked (42 corpus + 7 held-out) |
| Search cache | 87 `rec_cache` entries, 21 of them empty (no result passed the blocklist + relevance gate) |

The held-out guard (`build_concepts.corpus_sources()` refuses any corpus/held-out overlap) passes,
and `select_corpus()` now also drops `user_ingested` docs even if a URL is listed.

---

## 4. Deviations from DESIGN.md (and why)

| Deviation | Why | Resolve in |
|---|---|---|
| `link_confirm` runs on MODEL_QUALITY, not MODEL_FAST (CLAUDE.md prefers FAST) | FAST measured 89% precision, QUALITY 97% against the 95% target (M2). Recorded in CLAUDE.md and DESIGN §2/§10 | Keep |
| Spans only for graph-linked demands (the paragraph noisy-OR does count unlinked terms and context references) | The card needs a label and definition until explanations exist | M5 |
| `slowdown` (−0.02 on an unannotated paragraph) isn't computed | Needs dwell medians per reader; `annotation_dismissed` and paragraph-only `text_searched` are emitted since M6 | Post-hackathon unless M9 has room |
| Personas only for **anonymous** (demo) readers, via `?persona=` (default newcomer). Each (uid, persona) learns separately in `demo_graphs/{persona}` (θ too, now). Signed-in readers get onboarding + calibration since M7 | Decision 15 | Done (M7) |
| M7 onboarding: liked articles are picked from the library, not pasted URLs (DESIGN §8 said "optional liked URLs") | No ingest, no LLM cost, no SSRF surface at sign-up | Keep |
| M7 acceptance 1 and 2 ran with Auth-emulator "Google" accounts on the local harness (`make dev-emulator`), not real Google accounts | Creating real accounts isn't something the agent does; the live Google check covers the real flow once (Sourabh) | Live check after deploy |
| M7: new route POST /v1/me/consent (and /v1/calibration/skip, GET /v1/me/profile/edits, POST /v1/me/demo/reset) | Consent recorded by the API so the gate is enforced server-side | In DESIGN §8 |
| M7: profile_edit uses a flat response schema re-validated locally against the strict whitelist | Vertex returns 400 for tagged-union schemas and for an outer maxItems next to inner limits | Keep (DESIGN §15.3) |
| M7: edit-by-prompt for demo readers is session-only (their persona copy + session settings; reset button) | Sourabh's decision 2026-10-10 (judges are anonymous) | Keep (DESIGN §15.3) |
| M7: "this week" trend is a table only, no sparkline (the plan said sparkline with a table fallback) | The table carries the numbers accessibly; a sparkline is decoration for a few weeks of data | Revisit in M9 if time |
| M7: the live check is an API script plus a headless-browser pass on the live site, not one browser script | The demo flows are cheapest to assert through the API; the browser pass covers rendering, focus, axe and console | Keep |
| Per-minute rate limits are in memory per instance (≤ 3× a limit in the worst case); daily caps are in Firestore | Cheap; money-protecting caps are exact | Keep |
| A deleted account's still-valid ID token (≤ 1 h) is refused only on the instance that ran the delete | No per-request revocation check (an extra Auth call per request) | M9 if needed |
| Web search queries are `label + graph domain + format suffix`, not label + suffix only | Bare labels were ambiguous ("separation principle" returned a marine-engineering video). Domain is concept data, never reader data | Accepted as the rule (decision 4, DESIGN §16.3) |
| Web results must name the concept (relevance gate); results normalized and cached per (concept, format) with a cache version | Off-topic podcasts and stale thumbnails in the first live run | Keep |
| Up next format mix: preferred format 3 slots, then 2 and 1 by affinity; spare slots pass to the next format; at least one library and one web item when both exist | 2-per-format forced 2/2/2 for every reader, hiding preferences | Keep |
| Recommendations (M6.5), GET content routes, `/v1/recs/*` and publisher metadata were built ahead of the spec | Needed for the slice | Now documented: DESIGN §3, §4, §8, §16 (decision 9) |
| Publisher lead images are hotlinked with `referrerpolicy=no-referrer`, typographic tile on error | Fast demo; no image proxy | Keep (decision 3) |
| Content `source` adds `user_ingested`; build and held-out scripts exclude it | Reader-opened pages must never become corpus or held-out data | Keep |
| report_wrong goes through POST /v1/explain/{id}/report, not the event batch | It must evict the cache entries in the same call | Keep |
| Annotation response carries `definition`, `domain`, `prerequisites`, `debug` beyond the §8 shape | Kept in M5: the card shows them instantly and falls back to the definition (now in DESIGN §8) | Keep |

| Extension (M8-local) is unpacked, activeTab only: no allowlisted-domain activation, no host permissions, no automatic injection; not on the Web Store | Re-plan 2026-10-10 (decision 21): smallest permission set, no store review in the time left. DESIGN §11.3's allowlist activation is not built | Web Store release post-hackathon |
| Explanation prefetch (top 3 spans) runs in the web client after annotations load, not on the server | Keeps the annotations route LLM-free (CLAUDE.md); Cloud Run throttles CPU after a response, so server background prefetch is unreliable | Keep (DESIGN §7) |
| Verifier hedge/attribution/negation checks are scoped to the span's sentence in span mode, not the whole paragraph | A hedge elsewhere in the paragraph says nothing about the restated sentence; paragraph mode checks the whole paragraph | Keep (DESIGN §7) |
| A definition-only outcome after two rejected drafts is cached (no generated text) | Otherwise every hover on a hard span re-spends two generations; judge outages and the budget guard are not cached | Keep (DESIGN §7) |
| The plan's 400 KB extracted-text refusal (two-phase ingest) was not added | `clean_paragraphs` already truncates at 150,000 characters, which is tighter | Keep |
| The Background judge is its own prompt and route (`verify_background`), not a second verdict inside `verify.md` | Each part is verified on its own, and a Background check never re-judges a shared restatement | Keep (DESIGN §7, §10) |
| M6 shipped as one PR and one deploy, not two (A–C, then D) | All four parts were finished the same day; one deploy, one live check | Done |
| M6 accessibility: axe-core run in the live reader through headless Chrome instead of the Lighthouse CLI | Same engine (Lighthouse's accessibility audit is axe); no Lighthouse install in the repo | Keep |
| M6 keyboard: "Tab reaches pre-read links" not exercised live (the test article's pre-read steps are all definition disclosures, reached and toggled by keyboard); the "Yes" answer not checked live | Covered offline: vitest renders and clicks link steps; `tests/test_loop_e2e.py::test_corrections_change_the_next_load` covers both answers | Live check after deploy on an article with link steps if one is found |
| `explanation_reports` (review queue) stores the evicted entry with no user identifier, so it is outside export/delete; the report_wrong event itself is in `users/{uid}/events` | Shared content, not user data | Keep |
| M2.2: kind for the 3,327 pre-M2.2 concepts comes from `concept_jurisdiction`, not the v2 build cache | The build cache keys hash whole batches, so entries can't be mapped back to concepts | Keep |
| M2.2: glossary terms that exactly match an existing concept are dropped, not turned into link_merge-gated alias additions | Short acronyms are ambiguous across domains; dropping is safer | Keep |
| M2.2: growth is stored in Firestore `graph_growth/` and folded into `concepts.json` later (BUILD_PLAN said growth writes `concepts.json`) | The runtime account has no Storage write (an IAM change), and rewriting a 12 MB file per article is heavy | Keep (DESIGN §2) |
| M2.2: growth makes a fourth batched call, `link_confirm` on MODEL_QUALITY, to confirm each new concept (decision 36 tightening; the plan had 3 MODEL_FAST calls ≈ $0.004/article) | Raised judged precision from 87% to 97%; adds ≈ $0.004 and up to ~30 s per growing article (within growth's own timeout) | Keep; measure growth time before the flag flip |
| M2.2: growth timeout 30 s, not the plan's 20 s (still min(30 s, phase-2 time left − 5 s)) | Harness timing with growth on: 4 concepts in 20.0 s (cold instance), 3 in 6.9 s; 20 s would drop growth on a slow model answer | Keep; watch `growth_ms` live |
| M2.2: linker suite has 16 cases, not the planned 14 | Added a German chancellor negative and a second Chancellor case before any run | Keep |
| Design pass: the annotator's margin sidenote and phone bottom sheet already existed (since M5/M6, the sheet also in the extension), so no new `margin.ts` / `sheet.ts`; the card changes (pitch meter, Builds on, depth buttons, quote) live in `card.ts` and are opt-in (`loadShifted`) | Rebuilding working, tested placement code days before the freeze adds risk for no gain; the extension's behaviour is unchanged except level classes on marks, `renderPreread` skipping known steps, and card buttons now 44px tall everywhere (our target size; harmless in the extension) | Keep (DESIGN §9) |
| Design pass: the full extension build isn't checked here | This branch carries only the extension stub (it builds: `dist/background.js`); the real extension source lives on the paused `m8` branch and is built against annotator 0.2.0 at the m8 rebase | M8 rebase (Oct 14) |
| Design pass: annotator `package.json` 0.1.0 → 0.2.0 while the exported `ANNOTATOR_VERSION` goes 0.4.0 → 0.5.0 | The constant tracked API-shape versions since M5 and the extension reads it; both moved one step | Keep |
| Design pass: the margin "N notes for you" is a sticky contents list (mockup), not the old chips aligned with their paragraphs | The mockup's list reads better and the open card is already level with its line | Keep (DESIGN §19) |
| Design pass: "show less like this" only on For you rows; Topics and Saved rows have Save only | There is no library-article dismissal signal; adding one is new scope | Keep |
| Design pass: not built from the mockup: "Replay this week" on the map, and the illustrative "Gloss reads the transcript" notes for videos and podcasts | Neither is a BUILD_PLAN item; the mockup's content is illustrative | Recorded in the plan; not cut |
| Design pass: README hero screenshot still shows the pre-rename reader | Retaken with the deck and video on Oct 16 against the final demo data | Oct 16 |
| M7.5: pages brought in through POST /v1/recs/open ("Open here", Read any link, feed articles) or the extension (`NOT_CORPUS`) are private to the readers who brought them in; the library list and Up next hide them from everyone else. Production holds **7** `user_ingested` docs and 0 `extension` docs (read-only count, 2026-10-10), which disappear from other readers' libraries on deploy | A pasted page is a reader's choice, not editorial content, and M8 extension pages will be the same. Intended, not data loss: the docs stay reachable by id. M8 must keep "visible to the reader who brought it in" | Keep (DESIGN §17.4) |
| M7.5: feed phrases are "news this week" / "podcast" / "news explained", not the plan's "latest news" / "podcast episode" / "explained"; feed results also pass a page-shape check (article-shaped URL, no podcast chart or genre pages) and an English-only title check; feed news searches send no `exclude_domains`; YouTube feed searches ask for 4–20 minutes from the last 30 days; topics need interest ≥ 0.5 | Harness acceptance: the plan's phrases returned section pages, kids' videos and chart pages, and `exclude_domains` made Tavily return 0 articles of 9 (§17). Still only a taxonomy label + fixed phrase | Keep (DESIGN §17.1) |
| M7.5: an empty feed day entry may be searched again after an hour (≤ 2 searches per instance per (topic, format, day), ≤ 6 in all) | Tavily's results vary run to run; without a retry one bad sample empties a topic for the whole day | Keep (DESIGN §17.1) |
| M7.5: `seed_demo_feed` checks articles until 6 per topic pass (up to ≈ 20 fetch-and-extract checks per persona, not the plan's ≤ 12 in total), gained `--persona`, and its `--dry-run` performs the real searches (writing shared `rec_cache` entries and `ops/search` counters; only the `persona_feeds` write is skipped) | Feed searches return up to 10 articles and many fail the 400-word check (paywalls, 403); a dry run that can't see real results can't show what the snapshot will hold, and the real run the same day reuses the cache | Keep; production writes for the post-merge seeding are listed in §9 |
| M7.5: the web tests for the feed are logic-level (re-ask policy, waiting line, snapshot note, hiding a dismissed card in `lib/feedView.ts`), not rendered components; the `why` text is asserted in API tests | `apps/web` has no DOM test environment and adding one wasn't worth a new dependency days before the freeze | Keep |
| M7.5: For you searches only for the reader's topics (taxonomy label + fixed phrase), shared per day; demo personas get a pre-seeded snapshot and never search | Decisions 33 and 38: no reader data in queries, bounded cost, and judges always see a full page | Keep (DESIGN §17) |
| M2.2: variant-precision baseline is 83% on the newly frozen 150-mention sample, not M2's 93% | M2's figure used a different sample and candidate floor; not comparable | Keep |
---

## 5. Known issues and tech debt

| Severity | Issue |
|---|---|
| Medium | Cold start **6.0 s** after lazy imports (was 21.9 s, §11). Min instances 1 during judging removes it; the first new article on a fresh instance pays the deferred imports |
| Medium | **M9: Firebase App Check (reCAPTCHA Enterprise)** to stop scripted anonymous sign-ups. Shared anonymous caps bound the cost today (30 new URLs/day, 100 search calls/day), but a script can still mint accounts and burn those shared allowances for everyone |
| Medium | **M9: scheduled cleanup of anonymous users with no activity for 30 days** (Auth user + `users/{uid}`). "End demo" deletes on request; abandoned demo sessions pile up until then |
| Medium | "Open here" (M6, two-phase): the article shows in 1.4 s locally but took **7.3 s live** (M7.5 live check, first ingest on revision 00017: 6.8 s; a known pending link 0.2 s) on the first ingest of the new revision (phase 1 5.2 s server-side: deferred ingestion imports on a 1-vCPU instance shared with other readers' requests). A second live run (Wikipedia "Forward guidance", instance warm for health checks but its first ingest) gave the same: phase 1 6.6 s, article 7.5 s, notes 43.7 s. Phase-1 timing fields (`fetch_ms`, `extract_ms`) ship with M7 to split the cost; the likely cause is the deferred ingestion imports on a 1-vCPU instance. M9: preload them at startup while min instances = 1 (judging), where cold-start time no longer matters. Notes 20–55 s after; the reader shows "Preparing your notes… N s" |
| Low | Deleted-account revocation is per instance and in memory, so it is also lost on a restart. Seen in M6 local testing: a demo session deleted at 07:02:41 UTC sent one event batch at 07:10:19 after the dev server restarted, leaving `users/{uid}` + 6 `events` + 1 `demo_graphs/newcomer` (8 docs) under a deleted Auth user (Sourabh's own session). Left for the M9 anonymous cleanup unless Sourabh asks for a delete now; events expire by TTL in 90 days |
| Low | A cold explanation card (both parts missing) costs $0.0090 and p95 31 s (was $0.0070, 22 s): two judge calls. Reuse across readers repays it |
| Medium | Base difficulty `b` (LLM-estimated at build) drives every prior, so a wrong `b` mis-scores a concept for every reader without an edge. The linked-reference rule only trusts a prior ≥ 0.8 for that reason (DESIGN §6.7) |
| Low | Russell mislink fixed on `m2.2` (aliases moved to a new FTSE Russell concept); live once the seeded graph serves |
| Low | Persona templates are cached per API process: re-seeding needs a restart (or a deploy) to take effect, and demo readers who already have a copy keep their old one |
| Low | Recommendation format priors per persona are still the hand-set M6.5 values (`PERSONA_FORMAT_PRIORS`) |
| Medium | Held-out linking (M2.2, 30 articles, frozen graph): business 64% (target 75%), non-business 13% (floor 50%); glossary seeds don't match news phrasing. After growth 89% / 66%. Chancellor and levy fixed (decision 36) |
| Medium | Linker spot-check 3/10 wrong (target ≤ 2): links to a broader field or narrower concept, and to a generic seeded category ("molybdenum" → Element) |
| Low | Grown concepts can carry an invented label (1/30 in the judged sample: "Underground wildfire hot spots") |
| Medium | Growth doesn't dedupe concepts grown from the same article against each other: the live check grew both "Forever chemicals" and "PFAS" |
| Low | Grown/seeded prerequisites can be lexically near but wrong (live: PFOS → PHOSITA, a patent-law term; harness: Cilia waveform → Proper motion) |
| Low | `society` has 28 concepts, under calibration's 30, so it never appears in calibration (decision 37: domain kept as is) |
| Low | Anonymous traffic alone can use up the service's 100/day growth cap (30 × 5 = 150); accepted by decision 35, growth then stops for the day |
| Low | The cross-instance catalog refresh only covers articles that grew concepts; other new docs still need a restart on other instances |
| Low | Seeded multi-word everyday phrases ("Up and down", "One down") can be calibration items; the everyday-word rule covers single words only |
| Low | Publisher images set third-party cookies (Lighthouse best-practices 96 on the library). Broken hotlinks fall back to the typographic tile everywhere |
| Low | Web result quality varies (some generic podcasts, an exam-prep video); 21 of 87 cache entries empty |
| Low | Headlines keep publisher SEO suffixes (" \| Stock Market News"); we don't alter publisher text |
| Low | In-process catalog cache: docs ingested by another process need an API restart to appear (Open here appends directly) |
| Low | Up next article searches still send Tavily `exclude_domains`, which made the news topic return only section pages in M7.5 testing; Up next uses the general topic and its results looked fine in M6.5, but this is unverified (feed articles no longer send it) |
| Medium | Demo snapshots seeded 2026-10-10 are thin on articles for three topics: newcomer economics 1, trader business 1, policy student politics 0 readable articles (every topic has videos and podcasts). Before the Oct 16 re-seed: a second fixed phrase for thin topics in `seed_demo_feed` (≤ 1 extra search per thin topic; ask before the extra production searches) |
| Medium | Tavily is on the free Researcher plan: 398 of 1,000 monthly credits used on 2026-10-10. Realistic feed + Up next use is ≈ 15–30 credits a day; a day at the feed cap could use ≈ 40. If credits run out, searches fail and the feed serves cached and yesterday's entries |
| Low | A demo reader can hit the 60 requests/minute limit when a script opens many pages quickly (seen in the Design pass harness runs: the profile showed "didn't load" on a 429); real reading doesn't come close |
| Low | Refresher highlights are a minority (8–16% of shown spans at "For me" across the demo personas); some articles show only "new" highlights |
| Low | For you headline links are 27px tall text links (above WCAG 2.5.8's 24px, below our 44px control target, which applies to buttons) |
| Low | For you quality depends on Tavily's news results, which vary run to run (the same query gave 2 or 10 real articles); empty day entries are retried after an hour. "News this week" also pulls event pages ("Mental Health Week") |
| Low | A pasted page stays pending (not in the library) if its reader leaves before the notes finish and the analyse request never ran; the next open of that link analyses it |
| Low | The English-only filter checks script, not language: a Hinglish title in Latin script passes ("Health Insurance Claim Ka 10% Ab Aapko Dena Hoga?") |
| Low | Learning-goal resolution takes 8–19 s on the harness (embedding + link_confirm); the form says it is looking the idea up |
| Low | `rec_shown` relies on IntersectionObserver, which browsers pause in background tabs (seen in automated testing; real readers have the tab in front) |
| Low | Web main bundle 143.6 KB gzip (budget 150 KB) after the Design pass; For you, Saved and Profile are lazy chunks; the Cytoscape + dagre chunk is gone (the map is SVG) |
| Low | The weekly trend is per uid, so a demo session's trend mixes the personas it read as (the page says "this demo session") |
| Low | Calibration picks the most frequent concepts per domain, which occasionally surfaces a term like "Expiry days"; fine for a quick check, revisit with the gold set |
| Low | Firestore emulator fails contended transactions faster than production (three prefetched explanations reserving one daily counter); a jittered retry now wraps every transaction (no production occurrence in 7 days of logs) |
| Low | StarletteDeprecationWarning (httpx TestClient) in pytest output |

---

## 6. Config (names only, never values)

| Name | Purpose | Local | Cloud Run (currently deployed) | Secret Manager |
|---|---|---|---|---|
| ENV, LOG_LEVEL | runtime mode, logging | `.env` | yes | — |
| GCP_PROJECT, VERTEX_LOCATION | project, Vertex endpoint | `.env` | yes | — |
| MODEL_FAST, MODEL_QUALITY, MODEL_FALLBACK | LLM routes | `.env` | yes | — |
| MODEL_JUDGE | faithfulness judge (empty = MODEL_QUALITY) | `.env` (unset) | no (default) | — |
| EXPLAIN_DAILY_CAP, ANON_EXPLAIN_DAILY_CAP, ANON_GLOBAL_EXPLAIN_DAILY_CAP, RATE_EXPLAIN_* | uncached explanations per reader per day (100 / 40 anon / 400 all anon), explain requests per minute (60 / 30 anon) | defaults in `config.py` | defaults | — |
| MODEL_EMBED, EMBED_DIM | embeddings | `.env` | in `deploy.env.yaml`, not in deployed revision | — |
| CONCEPTS_URI | graph location | `.env` | in `deploy.env.yaml`, not in deployed revision | — |
| LINK_THRESHOLD, DEDUPE_THRESHOLD | linker tuning (calibrated 0.865) | `.env` | LINK_THRESHOLD 0.865 in `deploy.env.yaml`, not in deployed revision | — |
| LLM_DAILY_BUDGET_USD, LLM_TIMEOUT_S, LLM_MAX_RETRIES, MODEL_PRICE_OVERRIDES | LLM guardrails | `.env` | budget only | — |
| UID_HASH_SALT | log pseudonymisation | `.env` | yes, from secret | `uid-hash-salt` |
| TAVILY_API_KEY | web articles + podcasts | `.env` | yes, from secret | `tavily-api-key` |
| YOUTUBE_API_KEY | videos | `.env` | yes, from secret | `youtube-api-key` |
| ANON_INGEST_DAILY_CAP, ANON_GLOBAL_INGEST_DAILY_CAP, ANON_SEARCH_DAILY_CAP | demo-reader caps (3 per uid, 30 and 100 shared) | defaults in `config.py` | defaults | — |
| RATE_* (general 120/60 anon, annotations 60/30 anon, events 30) | per-uid per-minute limits | defaults | defaults | — |
| CORS_ORIGINS | allowed browser origins | empty (Vite proxy) | the two Hosting origins (`deploy.env.yaml`) | — |
| FIREBASE_PROJECT | ID-token project | defaults to GCP_PROJECT | default | — |
| VITE_FIREBASE_*, VITE_API_BASE | web Firebase config, API origin | `apps/web/.env.local` / `.env.production.local` (gitignored, `make web-config`) | baked into the Hosting build | — |
| SEARCH_DAILY_CAP, YOUTUBE_SEARCH_DAILY_CAP, SEARCH_TIMEOUT_S, RECS_CACHE_TTL_H | search guardrails | defaults in `config.py`, overridable in `.env` | no | — |
| INGEST_DAILY_CAP | new URLs per reader per day | default 20 | default | — |
| FEED_SEARCH_DAILY_CAP | For you search calls per day, all readers (inside the global search caps) | default 60 | default | — |
| GOAL_RESOLVE_DAILY_CAP | learning-goal resolutions per signed-in reader per day | default 10 | default | — |
| DEV_AUTH_BYPASS | curl/scripts only: a request **without** an Authorization header acts as an anonymous dev uid | opt-in; `make dev` no longer sets it | **must never be set**; refused at startup (verified live, §11) and re-checked per request | — |
| K_SERVICE | set by Cloud Run; used to refuse the bypass | — | automatic | — |
| CLOUDSDK_CONFIG, GOOGLE_APPLICATION_CREDENTIALS | isolated gcloud config + project ADC | Makefile exports, `.claude/settings.local.json` | — | — |

Identity: only `sourabhlocalllm@gmail.com` on `readlayer-sourabh-26` (see `CLAUDE.local.md`);
`make check-gcp` before any cloud command. No service-account JSON keys anywhere.

---

## 7. Costs so far

All spend so far is on **2026-10-04** (the only day in the ledger).

**LLM (Vertex): $10.67 total**, 2,769 calls, 6.8M tokens in / 2.9M out, 17 fallbacks.

| Task | Calls | Cost |
|---|---|---|
| link_confirm (MODEL_QUALITY) | 579 | $4.15 |
| extract_demands (all 309 ingests incl. held-out and Open here) | 369 | $2.72 |
| link_merge | 1,004 | $1.19 |
| concept_prereqs | 287 | $1.13 |
| concept_define | 203 | $1.04 |
| concept_wikidata | 65 | $0.07 |
| embeddings, smoke tests, retries | — | ≈ $0.37 |

Per-task figures come from the build cache and per-doc call records; they include cached
calls from earlier build runs, so they slightly exceed what any single run cost.

**Search: 164 calls** (Tavily 82 credits, YouTube 82 quota units = 41 searches + 41 duration
lookups). About half came from rebuilding the cache after two query changes. Steady state:
about 12 calls for a new article (3 concepts × 3 formats; YouTube counts 2), 0 when cached.

**Projection for the remaining milestones (rough):**

| Item | Estimate |
|---|---|
| M3, M4 (no LLM on the scoring path) | $0 LLM (spent: M4 used none) |
| M5 explanations + verifier + 40-case suite + 10 injection cases | $2–5 |
| M2.2 online growth (one batched concept_define per article) + held-out re-runs | $2–4 |
| M7 profile edits, onboarding | < $1 |
| M8-local extension ingestion (~$0.0075 per new article) | < $2 |
| M9 gold-set evals (30 articles × 2 personas) and demo pre-ingest | $3–6 |
| Hosting after submission: Cloud Run min-instances 1 during judging (Oct 19 – Nov 6) | ~$15–25 |
| **Total remaining** | **≈ $25–45 of the $300 credit** |

**For you (M7.5) search projection:** one search per (topic, format, day) is 14 × 3 = 42 a day
if every domain is someone's topic, but empty-entry retries allow up to 6 per (topic, format,
day), so the real ceiling is the feed cap: **60 calls a day** (`FEED_SEARCH_DAILY_CAP`), of which
YouTube can take up to 30 searches (60 calls) of its 90-search daily bucket, which Up next
shares; past the cap the feed serves today's or yesterday's entries. Realistic judging traffic
touches 4–8 topics: ≈ 10–20 Tavily credits and 4–8 YouTube searches a day. Demo snapshots are
seeded once per run (≤ 18 searches, plus ≈ 60 local fetch-and-extract checks, no LLM).

**2026-10-11 UTC (Design pass, local):** harness LLM ≈ $0.23 (explanations while testing, the verified "Say it simpler" checks, one Read any link ingest), 12 harness search calls (Up next on the reader page); refresher-share measurement and font metrics need no LLM. Production ledger for the UTC day: $0.06 (the before screenshots' demo reader and other traffic).

**2026-10-10 UTC (M7.5, local):** safety evals $0.53 (before) + $0.54 (after); harness LLM
≈ $0.52 after the restart (4 Read any link ingests with growth, 3 learning-goal resolutions,
reader-page explanation prefetches); the emulator ledger from before the restart was lost with
it (estimated < $0.10 and ≈ 40 search calls: snapshot seeding attempts and one 6-topic feed);
provider probes while fixing feed quality ≈ 30 Tavily credits and ≈ 6 YouTube searches (direct
calls, not in any `ops/search`); harness searches after the restart 48 calls (36 feed). Production
ledger for the UTC day: $6.71 LLM, 118 search calls, at the time of the review (the M2.2 and
earlier work of the same UTC day). Tavily: free Researcher plan, 398 of 1,000 monthly credits used
(2026-10-10, after the demo seeding). Post-merge production: `seed_demo_feed` 24 search calls (12
Tavily, 6 YouTube searches), `warm_demo` 24 cards, live check 1 ingest; the day's `ops/search`
reached 142 calls (feed 24).

Tavily cost depends on the plan in use (check the free monthly credit before M9); YouTube
quota is free within the daily buckets.

---

**2026-10-10 UTC (M7, so far):** profile-edit evals ≈ $0.01 (v1 rejected at $0, v2 $0.0047,
v3 $0.0049); emulator harness ≈ $0.10 over two runs (explanations and edits; its ledger is separate and was
seeded with production's $0.82, so with the cap at min($1, $8 − spend) checked against that seeded
ledger the harness had about $0.18 of headroom, not $1). Production spend today before M7 work: $0.82.

**2026-10-10 UTC (M2.2, local): ledger $5.43 for the day at the end of M2.2 work.** Linker
suite runs ≈ $0.31, held-out extraction freeze $0.08 + old-15 counts $0.07, held-out headline
runs ≈ $0.48, seeding dry runs $0.45 (final) + $0.74 (aborted all-pairs dedupe, fixed) + $1.72
(first full run), re-link dry run $0.53, profile_edit suite ≈ $0.01, harness ≈ $0.05, the second
judged growth run and the kind/jurisdiction backfill inside the seeding runs ≈ $0.49 (the rest of the
ledger; the rest of M6 earlier that UTC day was ≈ $0.50). Under the $8 cap.

**2026-10-10 UTC (rest of M6, local): ≈ $0.50 LLM.** Safety evals `explain-v4-split` $0.46,
local explanations while testing ≈ $0.03, one "Open here" ingest $0.0024. Under the $8 cap.

**2026-10-09 UTC (M5 day, IST 2026-10-10): $2.83 LLM**, 646 calls, 4 fallbacks (explain → FAST
on timeouts). M5 safety evals ≈ $2.53 (five full runs incl. the Pro judge at $1.12); local dev,
screenshots, demo exhibits and the live check ≈ $0.30. Under the $8 cap all day.

**Landing illustrations (2026-10-11, decision 44 V3):** `gemini-3.1-flash-image`, prompt
`landing-art-v1`, 5 images, **$0.34** (Sourabh approved up to 6 images / $0.60); two 429s,
unbilled. Details in DESIGN §20.1.

## 8. Guardrails in force

- **LLM budget:** `llm.py` refuses non-cached calls past `LLM_DAILY_BUDGET_USD` = 8. It is raised
  only for a specific run, with the reason recorded (here or in the PR), and set back after
  (decision 2). Spend ledger in `ops/spend/days`.
- **Search cap:** `SEARCH_DAILY_CAP` 300 calls/day across providers, `YOUTUBE_SEARCH_DAILY_CAP`
  90 searches/day; calls are reserved under a lock before they're made; past the cap the API
  serves cached (even stale) results and makes no call.
- **Ingest cap:** 20 new URLs per reader per day (3 for anonymous, 30 shared across all
  anonymous readers), on both POST /v1/content and "Open here", reserved in a Firestore
  transaction before ingesting and refunded on failure. Known URLs, including ones still pending
  analysis, are free. Two-phase: the slot is refunded if phase 1 fails; an article whose analysis
  fails 3 times (410) keeps the slot spent (the pending doc holds no uid to refund).
- **Consent gate (M7):** nothing about a signed-in reader is recorded before consent (events,
  page views, rec signals); corrections, settings and profile edits are 403; export/delete open.
- **Profile edits (M7):** 10 parses/day per signed-in reader; 3 per anonymous uid + 30/day shared;
  ≤ 30 names per edit, ≤ 3 link_confirm batches (≈ $0.02 worst case per parse); raw text and typed
  names never stored or logged.
- **Emulator harness (M7):** Settings refuse emulator hosts on Cloud Run or ENV=prod; the seed
  script reads production through a separate client and writes only to `demo-readlayer`; the
  harness budget is min($1, $8 − today's production spend).
- **For you (M7.5):** `FEED_SEARCH_DAILY_CAP` 60 calls/day shared by all readers, reserved under
  the same lock as the global and YouTube caps; each (topic, format, UTC day) is searched once
  for everyone, with at most 2 searches per instance (≤ 6 in all) when an empty entry is
  retried; past a cap or on a failure, today's or yesterday's entry is served; demo readers never
  search (snapshots). Queries are a taxonomy label plus a
  fixed phrase only (tested over all 14 domains).
- **Reading goals (M7.5):** signed-in readers only, after consent, ≤ 5 goals, 10 learning-goal
  resolutions/day (≤ 1 embed + ≤ 1 link_confirm each); the goal text is never stored or logged.
- **Anonymous search cap:** uncached web searches triggered by anonymous readers share 100 calls
  a day; past it they get cached web items and library items only.
- **Rate limits:** per uid per minute (general, annotations, events), tighter for anonymous.
- **Firestore (CLAUDE.md):** every user-data collection is in `USER_SUBCOLLECTIONS`, covered by
  export and delete; a test fails if anything is written under `users/{uid}` outside it.
  Rules deny all client access; raw events expire after 90 days (TTL).
- **Privacy:** no user identifiers, emails or reading history go to an LLM or a search provider
  (tested: outgoing queries contain only concept data). Logs carry `uid_hash` only.
- **SSRF:** every user-supplied URL, including "Open here", goes through `safe_fetch`.
- **Auth:** Firebase ID token on every `/v1` route (Google or Anonymous only, else 403); only
  `/health` is public. Tokens and emails are never logged or stored (tested, and checked in the
  live logs). CORS allows only the Hosting origins.
- **Corpus hygiene:** held-out URLs can never enter a build; `user_ingested` docs are excluded
  from both the corpus and the held-out evaluation.
- **Claude Code permissions:** destructive and billing gcloud commands denied; deploys, IAM,
  secrets and `git push` ask first (`.claude/settings.json`).

---

## 9. Next actions, in order

Autopilot order (decisions 33, 39): M2.2 (done) → M7.5 → Design pass → M8-local → M9.
BUILD_PLAN.md has the prompts. M6, M7 and M2.2 are merged and live.

| When | Action |
|---|---|
| Done | **M7** merged #16 and live; **M2.2** merged #18 and live (§16) |
| Now | **M7.5** merged #20 and live; steps (1)–(6) below done 2026-10-10 (§17). Step (7), Sourabh's Google check, done 2026-10-11. Post-merge steps, as run: (1) PR, milestone-reviewer SHIP, merge on green CI; (2) `make check-gcp`, deploy the API, then the web (Sourabh's yes on each); (3) `seed_demo_feed --dry-run`, then the real run: ≤ 18 searches (≤ 24 calls) counted in production's `ops/search`, ≤ 18 shared `rec_cache` feed entries, 3 `persona_feeds/{persona}` docs, ≈ 60 local fetch-and-extract checks, no LLM; check each persona has ≥ 2 readable articles per topic (re-run one persona with `--persona` if not); (4) record Tavily's plan and remaining credits here and in §7; (5) `warm_demo --dry-run`, then the real run (≈ 42 explanation entries, ≈ $0.25; today's production ledger is $6.71 of $8, so run it after 00:00 UTC if the deploy lands late on Oct 10 UTC); (6) `live_check_m7_5.py` (one demo reader pastes one non-business article, deleted after); (7) Sourabh's Google check: For you, one learning goal, open a feed article. Checkpoint end of day Oct 12 IST: if M7.5 isn't merged, ask Sourabh what to cut |
| Oct 11–13 | **Design pass** (decisions 39, 40): built and accepted on the harness on Oct 11 (§18), ahead of both checkpoints. Next: milestone-reviewer, PR and green CI, deploy API then web (Sourabh's yes), live check (one demo reader saves an article, presses Helpful and asks "Say it simpler" once, ≈ $0.01, deleted after) |
| After Landing ships, before M8 | **Wide layout** follow-up (decision 45): feed/library, profile and reader use the width; own plan, reviewer loop, PR. Pushes M8-local; if M8 or M9 is at risk, ask Sourabh what to cut |
| Oct 14 | **M8-local** (resume branch `m8`: plan approved; redaction and NOT_CORPUS done; keep M7.5's "visible to the reader who brought it in") |
| Oct 15 | **M9** hardening and evals, plus four M2.2 follow-ups required before the freeze (Sourabh, 2026-10-10): (1) merge check within one growth batch (same-article duplicates, e.g. Forever chemicals / PFAS); (2) validate grown prerequisites against the domain or drop low-confidence ones (PFOS → PHOSITA); (3) grown-concept precision on a fresh, independent sample of 30, reported with the 87% and 97% samples; (4) README and deck state the frozen-graph misses (64% / 13%) next to the after-growth numbers |
| Oct 14, start | **Rebase `m8` onto main** (it also changes `scorer.py`, `content/router.py`, `test_scorer.py`), then build the extension against annotator 0.2.0 |
| Oct 16 | Code freeze; demo seeding (re-seed persona templates, pre-ingest demo articles, **re-run `seed_demo_feed`** so the demo feed isn't dated "10 Oct" during judging, **`warm_demo --shifts`** after a dry run: ≤ 48 ±1-band Backgrounds, ≈ $0.20, so "Say it simpler" is warm in the video), README refresh and new screenshots, video, deck |
| **Oct 17** | **Submit** (deadline Oct 18): run a gitleaks scan over the full history, then make the GitHub repo public (decision 44; the landing links to it) |

**Video line:** sign in as a demo persona → library → open an article → hover and open notes →
"Not really" on a prompt → reload shows the change → Up next → **For you** (demo snapshot with
its note; then a Google reader's live topics and a "helps your goal" line) → **Read any link**
(paste a non-business article; it opens in seconds and concepts grow) → profile: **reading
goals** (a habit and "understand X" with progress) and the knowledge map's goal view. Design
pass additions: a note's "Say it simpler" (warmed), "What this article changed" with an Undo,
and the all-topics map with ready-to-learn rings.

**If late:** stop and ask Sourabh what to cut (decision 27). The old cut order (edit-by-prompt →
knowledge-map graph → M2.2 online growth → extension popup extras) is no longer applied
automatically.

**You, by hand:** label the gold set (30 articles × 2 personas, with your teammate, from Oct 12);
record the video; build the deck; Cloud Run min instances 1 for Oct 19 – Nov 6.

---

## 10. Decisions (1–14 decided 2026-10-04, later ones dated)

| # | Topic | Decision |
|---|---|---|
| 1 | PR #9 | Squash-merged as one commit `M6-slice: vertical slice, redesign, recommendations`, body listing the four parts |
| 2 | LLM budget cap | Back to 8 (edited by hand in `.env`). Raised only per run, with the reason recorded |
| 3 | Publisher images | Keep hotlinking with `no-referrer`; typographic tile when an image fails (done for library, reader and Up next) |
| 4 | Search queries | Concept label + graph domain + format suffix is the rule (DESIGN §16.3) |
| 5 | Search keys | Tavily and YouTube keys move to Secret Manager at the first deploy |
| 6 | "Open here" latency | Two-phase loading, in the rest of M6 |
| 7 | Personas | Demo mode served through Firebase Anonymous sign-in once M3 auth exists; after M4 they are seeded reader graphs instead of hand-set θ |
| 8 | Held-out set | Grows from 15 to 30 articles in M2.2 |
| 9 | DESIGN.md | §16 (recommendations) and the §3/§4/§8 additions written now |
| 10 | First real deploy | Done at the end of M3, with auth and the per-user cap on POST /v1/content |
| 11 | Personas (M3) | Anonymous demo readers only, `?persona=` per request, hand-set θ fixed; Google readers are themselves (θ = 0 until M7) |
| 12 | Anonymous limits (M3) | 3 new URLs/day per uid, 30/day shared, 100 uncached search calls/day shared, tighter per-minute limits; "End demo" deletes the session's data |
| 13 | Anonymous web search (M3) | Cached web results always served; new searches count against the shared anonymous cap; past it, library items only |
| 14 | M9 tech debt (M3) | Firebase App Check (reCAPTCHA) against scripted anonymous sign-ups; scheduled cleanup of anonymous users inactive for 30 days |

| 15 | Demo persona storage (M4) | One doc per (uid, persona), `users/{uid}/demo_graphs/{persona}`, copied from the read-only `persona_templates/{persona}` on the first event (reads use the template). ≤ 5 evidence per edge, 800 KB guard |
| 16 | "Knew this" (M4) | The reader's latest explicit word wins: a concept last marked knew_this / "I know this" is not annotated until contrary explicit evidence (DESIGN §6.6) |
| 17 | Linked references (M4) | Option C: a linked context reference uses the concept's p_know only with a KNOWS edge or a prior ≥ 0.8 (DESIGN §6.7, five cases recorded there) |
| 18 | Prompts while paused (M4) | No "Know this?" prompt while learning is paused, so a paused reader's page loads write nothing |
| 19 | Deploy guard (M4) | `make deploy-api` / `deploy-web` refuse while a deploy runs on this machine, a Cloud Build is in progress or the API is mid-rollout |
| 20 | Re-plan (2026-10-10) | M5 Oct 10; rest of M6 Oct 11; M7 trimmed Oct 12–13; M8-local Oct 14; M9 + M2.2 trimmed Oct 15; demo, README, video, deck Oct 16; submit Oct 17. M2.2 online growth and the bigger held-out set deferred |
| 21 | Extension (2026-10-10) | M8-local replaces M8: unpacked via Developer mode, `activeTab`/`scripting`/`storage` only, no host permissions or automatic injection; auth via "Connect extension" for demo and Google readers; popup with sign-in state, persona, density, profile link. Web Store release post-hackathon |
| 22 | Cut order (2026-10-10) | If late, cut in this order: edit-by-prompt, knowledge-map graph, M2.2 online growth, extension popup extras |
| 23 | Persona frames (M5) | Newcomer software, trader cricket, policy student law (`PERSONA_THINKS_IN`, code not template data) |
| 24 | Paragraph explainers (M5) | API, cache and evals in M5; the margin-marker UI in the rest of M6 |
| 25 | Judge model (M5) | `MODEL_JUDGE` env var, default MODEL_QUALITY; compared against Gemini 3.1 Pro on the safety suite (evals/report.md) |
| 26 | Eval integrity (M5) | Cases committed before the first model run; any prompt change bumps its version and is reported before/after in evals/report.md; cases are never edited to pass |
| 27 | Autopilot (2026-10-10) | Plan-reviewer loop replaces plan mode and plan approval; milestone-reviewer SHIP + green CI before merge; deploys and `git push` still need Sourabh's yes; production writes only within each plan's counts. M7 keeps the knowledge map and edit-by-prompt (no cuts without asking). Log: `docs/AUTOPILOT_LOG.md` |
| 28 | Shared restatement (M6) | "What the author is saying" is one cache entry per (span, style) for every reader; the Background is per (band, frame, style). Restatement rejected → definition card; Background rejected → restatement with the definition in that panel. One cap count per request |
| 29 | Two-phase "Open here" (M6) | Two synchronous requests (no work after a response on Cloud Run): phase 1 stores `pending_contents/`, phase 2 under a 150 s lease with a 120 s timeout; 3 counted failures → 410 |
| 30 | Edit-by-prompt for demo readers (M7, Sourabh 2026-10-10) | Allowed, session-only: changes the session's persona copy and settings, never the template; "Reset persona" returns to the original; caps 3/uid, 30/day shared |
| 31 | M7 harness (2026-10-10) | Local end-to-end on Firestore + Auth emulators seeded read-only from production; emulator "Google" readers for acceptance; real-account check by Sourabh after deploy |
| 32 | M2.2 scope (Sourabh, 2026-10-10) | Full scope, not trimmed: online concept growth, jurisdiction in `link_confirm`, strictness, the Russell mislink, a 30-article held-out set and ≥ 75% linked on it. Supersedes the M2.2 part of decisions 20 and 22 |
| 33 | Open domains, new order (Sourabh, 2026-10-10) | Not a business-only reader. M2.2 adds a fixed 14-domain taxonomy (old four ids kept), growth into it, non-business held-out articles and a per-domain report. New M7.5: "For you" feed (Tavily, YouTube; taxonomy topic names as the only query text; shared cache per topic/format/day), "Read any link" box, reading goals (`users/{uid}/goals`). Demo personas unchanged; open domains for Google readers. Order M2.2 → M7.5 → M8 → M9; if the Oct 16 freeze is at risk, ask what to cut |
| 34 | M2.2 targets with open domains (Sourabh, 2026-10-10) | New domains are seeded from Wikipedia glossaries (medicine, computer science, cricket, association football, biology, law, …) fetched through safe_fetch, parsed deterministically from definition lists, then the normal dedupe/define pipeline; concept counts and production writes shown to Sourabh before writing. Per domain on the 30-article held-out set: (1) frozen-graph link rate, the headline: business ≥ 75%, non-business aim 60%, **under 50% → stop and tell Sourabh**; (2) after-growth link rate, labelled production behaviour (links to concepts grown from the same article never count in the headline); (3) precision on a judged sample of grown concepts ≥ 90% |
| 35 | Growth for demo readers too (Sourabh, 2026-10-10) | Concept growth applies to any ingest that passes the existing caps, anonymous/demo readers included (3 per uid, 30 shared per day already bound the cost); judges mostly use demo mode and must see growth on a pasted link. Persona graphs stay as they are; only the global concept graph grows. Supersedes the "Google readers only" growth gate in the M2.2 plan |
| 36 | M2.2 after the stop rule (Sourabh, 2026-10-10) | Frozen-graph headline missed (business 64%, non-business 13%) even with 1,874 glossary seeds: glossaries hold textbook terms, news uses specific phrases. Go with the recommendation: tighten growth until grown-concept precision clears 90%, ship seeding plus growth (judges see concepts grow on a pasted link), report the headline miss honestly, move on to M7.5. News-corpus seeding per domain not done (about a day; freeze risk) |
| 37 | M2.2 open questions (Sourabh, 2026-10-10) | Generalise `explain`, `restate`, `verify`, `verify_background` beyond business news inside M7.5, with before/after safety evals on the frozen cases (≈ $2) and a `warm_demo` re-run as a production write. Keep `society` (fills through growth; hidden in calibration until 30 concepts) |
| 38 | Demo feed (Sourabh, 2026-10-10) | Demo personas get a predefined (pre-seeded) For you feed, served without live searches, with a subtle note that the picks were prepared in advance and may be dated, and that signing in gives a live feed for the true experience |
| 39 | Design pass milestone (Sourabh, 2026-10-10) | Right after M7.5 is merged and deployed, before resuming M8: a Medium-style reading product (tokens and type, library as a feed with For you / Topics / Saved, 680px reader with a sticky action bar and highlight-style annotations, profile with domain cards and a redesigned knowledge map that is never empty). Same reviewer loop plus before/after screenshots (desktop, mobile, dark). Keep accessibility, the bundle budget, two-phase loading and annotation behaviour. M7.5's own web parts stay functional and accessible, not polished, since the design pass rebuilds them |
| 40 | Design pass additions (Sourabh, 2026-10-10 22:06) | Display name **Gloss** (logo, titles, meta, copy, README, deck; Firebase project, URLs, repo and ids unchanged). Visual target `docs/design/mockup.html` (Schibsted Grotesk UI + Source Serif 4 reading; rebuilt in our components, not copied). Mascot **Margo** (the mockup's `margo()` SVG, four moods + 16px mark) in the logo, favicon, extension icon, reader margin header, notes-loading, end-of-article recap, empty and error states; never in article text or on note cards, no animation while reading, aria-hidden. Reader details: "Before you read" as a path, two highlight styles (new vs refresher), "N notes for you" margin list, card level with its line plus pitch meter, "Builds on", "Say it simpler" / "Go deeper" (one band lower/higher through the verified path, cached by band, counted against the explain caps), author quote, "What this article changed" recap with undo and read/watch next. Mobile: bottom-sheet card, paragraph markers only where a paragraph note exists. Details in BUILD_PLAN Design pass items 6–10 |
| 41 | Landing and onboarding milestone (Sourabh, 2026-10-11) | After the Design pass ships and before M8: a landing page at "/" for signed-out visitors (hero with a static live mini-demo and persona toggle, problem, solution, how it works, trust with real eval numbers, what you can read, CTA, footer; no LLM/API calls; LCP < 2.5 s mobile, JS < 60 KB) and onboarding in 2 screens (field, topics, optional free text resolved to concepts, inline consent; then live web results with read/not-for-me and one Know this? per card replacing calibration, and a one-sentence readback). Free text never sent or stored. Full spec in BUILD_PLAN. Ask before cutting if M8/M9 are at risk |
| 42 | Free-text topic fallback, a narrow documented exception to the free-text rule (Sourabh, 2026-10-11) | In onboarding, a phrase that matches no concept is mapped to one of the 14 topics: first a small deterministic alias list (e.g. F1 / Formula 1 / IPL → Sports, startups / VC → Business; no model call); otherwise only the phrase is embedded (MODEL_EMBED, no uid or other reader data, not stored, never sent to search) and mapped to the nearest topic scope line above a similarity threshold set from test phrases; below it, "didn't recognise". The mapping is shown back ("F1 → Sports") and can be changed. The consent line says what you type is matched to topics by our model and isn't stored. Recorded in DESIGN §11, with a test that no raw free text reaches search or Firestore. Also approved: warming 5 landing-demo notes (markets article p5) as a production write (done: $0.03) |
| 43 | Checkpoints for /clear (Sourabh, 2026-10-11) | At the end of each milestone (merged, deployed, STATUS and AUTOPILOT_LOG updated, all committed) and at natural mid-milestone checkpoints (all committed, the log names the exact next step), stop and say "READY FOR /clear" with a one-line resume note. Added to the CLAUDE.md working agreement |
| 44 | Landing visuals and light default (Sourabh, 2026-10-11) | Keep the landing's structure, copy, headline, Read-as demo and the side-by-side; add visuals: a large Margo character in the hero (pointing at the note, mood follows the persona toggle) and the final CTA; a laptop + phone product shot of the real reader (AVIF/WebP 1x/2x, source credited); three problem illustrations from Google's image model on Vertex (flat ink + teal, Margo as character reference, credited in the footer; model, prompts, cost in DESIGN/STATUS); How it works as a 2×2 grid of 3–5 s silent looping clips from the real app (WebM + MP4 ≤ 400 KB, poster only under reduced motion); a full-width teal trust band with the eval results as large figures; alternating paper/wash bands. Budgets unchanged (LCP < 2.5 s mobile, first view < ~1.5 MB, below-fold lazy, axe 0). **Light is the default theme**: dark only via the toggle, not the OS. GitHub links stay; the repo goes public at submission after a gitleaks scan (M9). Plan amendment in `docs/plans/landing-onboarding.md` |
| 45 | Wider layouts (Sourabh, 2026-10-11) | Pages feel cramped with large side margins on wide screens. Landing (this milestone): section containers up to ~1280px, hero a 50/50 split (copy · big Margo + demo), illustrations, clips and the teal trust band may be full-bleed, fluid spacing with clamp(). Feed/library (container ~1280px, wider rows, filled sidebar, a third column at ≥ 1440px with a "Your map this week" mini-map and goals), profile (more domain-card columns, knowledge map full container width and taller) and reader (text column stays ~680px; note margin on the right as now; at ≥ 1280px a slim left rail with contents, reading progress and notes count): a separate **Wide layout** follow-up after Landing and onboarding ships and before M8 (not small enough for the same PR: new third column, reader left rail, profile restructure), own plan and reviewer loop. Screenshots at 1280, 1440, 1920 and 390 |

No decisions are open.

---

## 11. M3 acceptance (verified 2026-10-04/05)

**Live URLs:** web https://readlayer-sourabh-26.web.app · API
https://readlayer-api-d2sfihz3za-el.a.run.app (revision `readlayer-api-00010-tiw`).

| Check | Result |
|---|---|
| `reader/` covered by tests: prior, Beta init, bands, forgetting (90 days halves the distance to the prior), evidence weights, band_prev/band_changed_at, Elo | Pass (`test_reader_model.py`, `test_reader_logic.py`) |
| Replaying an event batch changes nothing | Pass in tests, emulator and live (1 applied, then 0) |
| Export returns every user doc incl. weekly and settings; delete leaves nothing under `users/{uid}` and removes the Auth user | Pass against the Firestore + Auth emulators (`make test-emulator`) and live (anonymous ×3 by script, your Google session by hand) |
| Logs carry `uid_hash`, never an email or token | Pass in tests; live: 177 entries, 0 JWTs / Bearer / emails, 0 secret values |
| Summary template deterministic, no LLM call on the profile path | Pass (test patches `llm.run` to fail) |
| GET /v1/me/graph?domain=X: ≤ 60 nodes, closed edges, acyclic | Pass (tests incl. a 150-node graph) |
| learning_paused → POST /v1/events `applied: false`, nothing written; PATCH /v1/me/graph still applies | Pass |
| Anonymous demo per persona = local slice annotations; rec signals and ingest counts survive restart, appear in export, gone after delete | Pass: live, all 3 personas identical to the local placeholder output; restart test; export/delete |
| POST /v1/content and /v1/recs/open: 401 without token, 429 on the 21st new URL | Pass in tests (and 4th for anonymous, shared anonymous cap). Live: 401 checked; the cap wasn't exercised live (each new URL costs an LLM ingest) |
| Anonymous web-search sub-cap (100/day shared), library-only past it | Pass in tests; live counter `ops/search/days/*.anonymous` = 36 after the checks |
| `/health` 200; every /v1 route 401 without a token (forged token 401) | Pass live (14 routes) |
| Web on Hosting signs in anonymously, opens an article with annotations and Up next incl. web items | Pass (locally against real Firebase in Chrome; live by script and by your session) |
| Google sign-in | Pass: your session (Google, no persona) read, sent events, exported, deleted; 0 Auth users and 0 user docs remain |
| No Tavily/YouTube key in the web bundle, browser or logs | Pass: secrets used as grep patterns against `dist/` and live logs, 0 matches |
| Request from another origin refused by CORS | Pass live: preflight from evil.example 400 without ACAO; Hosting origin 200 |
| Deployed revision refuses to start with DEV_AUTH_BYPASS=true | Pass live: tagged no-traffic revision `-00004` raised the Settings error, startup probe failed, 503; revision deleted, env restored |
| Firestore rules deny all client access | Pass (emulator REST: reads and writes 403); deployed |
| 90-day TTL on raw events | Enabled (`events.expire_at`) |
| LLM budget guard on the live path | Pass, by accident: "Open here" on a new URL got 503 `llm_budget_exceeded` (today's ledger $10.67 > prod cap $8) and the ingest slot was refunded |

**Cold start** (Cloud Run "Starting new instance" → startup probe succeeded, 1 vCPU):

| Build | Startup CPU boost | Start → ready |
|---|---|---|
| M3 first deploy (`-00003`, `-00005`), everything imported at startup | on (gcloud's default; already on) | **23.6 s, 21.9 s** |
| Same image, boost off (`-00009`, test revision, deleted) | off | 21.3 s |
| Lazy ingestion imports + LiteLLM (`-00010`, live), at deploy rollout | on | **6.0 s** |
| Same, true scale-from-zero after 11 h idle (2026-10-05 06:22 UTC) | on | **9.2 s** start → ready; client saw 9.7 s for `/health` |

The ~21 s was almost all before uvicorn started: reading spaCy, LiteLLM and friends off the image
the first time, not CPU (boost alone saved < 1 s). Read paths now never import spaCy, trafilatura,
wordfreq or LiteLLM (`tests/test_lazy_imports.py` checks it in a fresh interpreter); locally
`import app.main` went from 1.6 s to 0.33 s. App startup (graph load from GCS) is ≈ 0.5 s. Warm
`/health` 0.05–0.12 s; first library list per instance ≈ 2.1 s (loads 309 docs), then 0.15–0.3 s.
**First new article ("Open here") on that cold instance** (2026-10-05, Wikipedia "Liquidity
trap", POST /v1/recs/open): **42.1 s** end to end (server 42.4 s). **spaCy model load 0.94 s**
(`spacy loaded` log line), about 9 s into the request, after the fetch, extraction and the
deferred imports; `extract_demands` 15.3 s (MODEL_FAST), `link_confirm` 3.4 s; the rest is
LiteLLM's first import, embeddings and linking. Model cost ≈ $0.017. The article then had 27
annotations (0.28 s); the ingest counter showed 1 and the test user was deleted. Min instances 1 during judging (Oct 19 – Nov 6) removes cold starts.

**M3 spend:** $0 LLM (the one ingest attempt was refused). Search: 36 calls, all anonymous.

---

## 12. M4 acceptance (verified 2026-10-05)

**Live:** API revision `readlayer-api-00009-gkf`, web bundle `index-Dfwq_13e.js`. Persona
templates seeded to `persona_templates/{newcomer,trader,policy_student}` from graph `2026-10-04`.

| Check | Result |
|---|---|
| DESIGN §5 worked example (yield curve 0.68 shown, inflation 0.19 skipped, paragraph 0.741 → 0.834 with the structure term) | Pass (`test_scorer.py::test_design_worked_example`; the example is now written into DESIGN §5) |
| Same reader + article → identical annotations, whatever the demand order | Pass |
| Every cap: 1 span / 80 words, ≤ 2 per paragraph, 1 marker / 3 paragraphs, first occurrence, prompt 1/article and 3/day, pre-read ≤ 3 steps stopping at p ≥ 0.7, offset clamp ±0.15 | Pass (`test_scorer.py`, 33 tests) |
| Loop closed: knew_this / PATCH /v1/me/graph / explain_opened change the next load; personas learn separately; Google readers start neutral | Pass (`test_loop_e2e.py`, API + in-memory store) and the Firestore/Auth emulators |
| `placeholder.py` deleted; demo personas = seeded graphs, copy-on-write | Done. Reading writes no copy; the first event writes `demo_graphs/{persona}`; export and delete cover it |
| **Scoring p95** (pure scorer; target < 150 ms for 1,200 words) | Local: **0.19 ms** (synthetic 3,300-concept graph, test) and **0.25 ms** (24 real 1,000–1,400-word articles). Cloud Run: **1.0–1.3 ms** (the API's rolling p95 log line, windows of 50–200) |
| **Annotations endpoint p95 on Cloud Run**, incl. the Firestore state read and the page-view write (measured on revision `-00008-d7b`, before the option C rule change, which adds one comparison per reference) | Server (request logs, n = 110): median **53 ms**, **p95 99 ms**, max 135 ms. Client in India incl. network (n = 100, 10 demo users × 10): median 95 ms, p95 121 ms |
| Personas recognisably different (all 310 corpus articles, balanced) | Trader vs policy student identical sets **8/310** (mean Jaccard 0.15); newcomer vs trader 28/310 (0.44); newcomer vs policy student 34/310 (0.46). Mean spans: newcomer 11.9, trader 6.4, policy student 6.3. Before M4 (θ-only placeholder): 27, 35, 92 identical |
| Live: three personas on one article (UK interest rates explainer, 1,136 words) | Pass: newcomer 12 spans, trader 7, policy student 4, three distinct sets |
| Live: "Knew this" persists across reloads | Pass: trader tapped *Federal Reserve*; gone on reload 1 and 2; newcomer persona and a separate demo session unaffected. (On the first-draft rule, a tap on *Monetary Policy Committee* also dropped two related policy concepts as policy θ rose) |
| Template sizes (one Firestore doc each) | newcomer 109 edges **18.3 KB**, trader 86 edges **14.5 KB**, policy student 115 edges **19.3 KB** (≤ 1.9% of 1 MiB) |
| Demo doc size guard | 500 events over 250+ concepts on one persona stay under 800 KB with ≤ 5 evidence per edge (test); the drop order (oldest low-confidence non-seed first, never this batch's edges) is tested with a lowered limit |
| Linked-reference rule | Option C (DESIGN §6.7): measured four variants on 310 articles × 3 personas; the five judged cases are recorded in DESIGN. The Russell Indexes mislink went to issue #6 |
| Deploy guard | `make deploy-guard` (run by both deploy targets): passes when idle; refuses with the process listed when a deploy runs on this machine (tested with a fake process). The Cloud Build and rollout branches ran live and found nothing in flight; not forced |

**Incidents.** (1) Two overlapping `make deploy-api` runs: the first was still uploading and
invisible in Cloud Build, so a second was started; it was stopped and its build cancelled before
deploying. The deploy guard came out of this. (2) A live-check script hit the anonymous
annotations rate limit (30/min) and exited before deleting its 4 test users; they were found by
creation time and deleted (Firestore tree + Auth user). All later scripts delete in `finally`;
0 test users remain. One unrelated anonymous browser session from 17:32 UTC was left alone.

**M4 spend:** $0 LLM. Three Cloud Builds (one cancelled), Firestore reads for the corpus analysis.

---

## 13. M5 acceptance (2026-10-10)

**Built.** POST /v1/explain (span and paragraph mode) and POST /v1/explain/{id}/report;
`app/explain/` (inputs, deterministic checks, judge, service with single-flight), cache
`explanations/*`, review queue `explanation_reports/*`, per-uid daily generation cap
(`explain_counts`, in export/delete), `MODEL_JUDGE`, per-route thinking level (unused). Card:
Background (tinted panel, analogy frame tagged) and What the author is saying (accent rule),
definition shown at once in the Background panel and replaced in place, skeleton with "checking
it against the article", definition-only fallback, Knew this / Helpful / This is wrong with an
inline confirmation, sidenote in the margin at ≥1200px, popover (360px, height capped to the
room it has), bottom sheet on phones, persona switch reloads an open card. Web prefetches the
top 3 spans after annotations load.

**Safety evals** (`apps/api/evals/`, cases committed before the first model run; full table and
per-case detail in `evals/report.md`, prompt history in `evals/changelog.md`):

| Run | Prompts | Judge | Adversarial rejected | Good accepted | Judge errors | Pipeline first / retry / definition | Injection safe | $/explanation | p50 / p95 |
|---|---|---|---|---|---|---|---|---|---|
| baseline | explain-v1 | 3.8-flash | 15/15 | 25/25 | 0 | 22 / 1 / 2 | 10/10 | 0.0064 | – |
| flash-judge-timed | explain-v1 | 3.8-flash | 15/15 | 21/25 | 4 (timeouts) | 23 / 0 / 2 | 10/10 | 0.0063 | 14.1 / 68.2 s |
| pro-judge | explain-v1 | 3.1-pro-preview | 15/15 | 25/25 | 0 | 24 / 0 / 1 | 10/10 | 0.0165 | 20.4 / 40.3 s |
| explain-v2 | explain-v2 | 3.8-flash | 15/15 | 25/25 | 0 | 24 / 1 / 0 | 10/10 | 0.0070 | 18.0 / 38.9 s |
| **explain-v3 (shipped)** | explain-v3 | 3.8-flash | **15/15** | **25/25** | 0 | **25 / 0 / 0** | **10/10** | **0.0070** | **14.9 / 21.8 s** |

- Deterministic checks caught 12 of 15 adversarial cards, the judge 14; A06 ("said he would hold
  out" → "decided to hold out") passed both judges and was caught only by the attribution check.
- Judge: Gemini 3.1 Pro gave identical verdicts at ≈ 4× the judge cost and a slower median, so
  MODEL_QUALITY stays the judge (decision 25).
- No planted instruction appeared in any shown card or any rejected draft.

**Cost.** ≈ $0.0070 per verified explanation (generate + checks + judge, retries included).
Prefetch across the demo: 6 articles × 3 personas × 3 spans = 54 explanations ≈ **$0.38** once,
then cache hits. The $8 daily cap covers ≈ 1,100 new explanations a day (shared with ingestion).
M5 spend: evals ≈ $2.53, local dev and screenshots ≈ $0.30.

**Front-end review** (`make dev`, headless Chrome over CDP, light and dark, 1440 / 1024 / 390):
redundant definition merged into the Background panel; Background shortened (explain-v2) and made
level-aware (explain-v3, a trader who "can explain" gets nuance, not a definition); report
confirmation restyled; popover at 1024px no longer runs off the top; rail chips step back under
an open sidenote. A scripted persona switch timed out once while the dev API rate-limited the
script (429s in the log); the rerun passed and the path is unit-tested.

**Live (2026-10-10, API `readlayer-api-00010-9tr`, web `index-uEFIQ12G.js`)**, by
`scripts/live_check_explain.py` (one anonymous user, deleted after: DELETE /v1/me 204):

| Check | Result |
|---|---|
| Generate | Trader card for "FIIs" (band can explain, cricket): miss, verified first draft, **23.5 s** client (server 23.4 s, of which 15.3 s model time: explain 8.6 s + verify 6.7 s; the rest not broken down) |
| Cached hit, no LLM call | Newcomer card: **145 ms / 191 ms** client, 41–60 ms server; the logs show no `llm call` for any of the 3 hits |
| Personas get different Background | 3 distinct Backgrounds (software / cricket / law); the trader at "can explain" got one sentence of nuance, the others a definition plus analogy |
| "This is wrong" | `{evicted: true, event_applied: true}`, review doc written, next request regenerated (**14.2 s**, verified first draft) |
| Privacy | App log lines: 0 emails, 0 tokens, 0 article text; the only email-shaped strings are in GCP's own audit logs for the deploy |
| Cache hit rate | `ops/explain/days/2026-10-09` (local dev + live, same Firestore): **135 hits / 38 generated = 78%**, all 38 verified first draft, 1 report |

Demo exhibits in `apps/api/evals/demo.md`: "depth adapts" (basis points: unaware / can explain /
heard of) and "three frames" (credit default swap, unfamiliar to all three: failover / batter
insurance / indemnity analogies), plus a real rejection (the judge refused a draft that "fixed" a
garbled source phrase; the reader got the definition).

---

## 14. M6 (rest) acceptance (2026-10-10, local and live)

**Built.** Annotator 0.4.0: paragraph markers (pilcrow in the margin; float right below 900 px)
opening the card in paragraph mode, "Know this?" chip (Yes / Not really → PATCH /v1/me/graph),
pre-read card (`renderPreread`, links or definition disclosures), reading signals
(`paragraph_dwell`, `text_searched`, `annotation_dismissed`), inserted controls never part of the
article text (`data-rl-ui`), Helpful with a text label. Web: event batching with paragraph_id,
words and ms, hide/pagehide flush and one retry; two-phase reader. API: two-phase ingest
(`pending_contents`, POST /v1/content/{id}/analyse), paragraph-only `text_searched`, shared
restatement (`restate`, `verify_background`). Tests: API 435, annotator 36 (incl. axe-core).

| Check | Result |
|---|---|
| Markers, pre-read and prompt render for a persona that triggers them | Newcomer on "Government extends RoDTEP…": pre-read 3 steps, 2 markers, prompt on SEZ |
| Keyboard reachable | Marker: Enter opens with focus in the card, Tab cycles its buttons, Escape closes and returns focus to the marker; Tab reaches the chip's buttons |
| No serious axe violations | axe-core in the live reader (incl. contrast, paragraph card open): 0 violations in light 1440, dark 1440, light 390 (after hiding rail chips under an open card; they failed contrast at 0.28 opacity since M5) |
| Answering the prompt changes the next load | "Not really" on SEZ → reload: SEZ is a span, the prompt slot moved to "Export Oriented Units" |
| "Open here" shows the article before its notes | New URL (Wikipedia "Yield curve control"): article **1.39 s** after the click, notes **24.7 s**, no reload; pending doc deleted, $0.0024 |
| Events batched and applied once | One 5 s batch: paragraph_dwell ×5, text_searched (unmarked paragraph), explain_opened, annotation_dismissed; replay → `events_applied: 0` |
| Shared restatement | Newcomer then trader: 3 restatements for 3 distinct spans, 4 Backgrounds; the shared span's restatement made once |
| Safety evals (`explain-v4-split`) | Adversarial 15/15 (judge 15), good 25/25, new Background suite 5/5, injection 10/10; $0.0090 per cold card, p50 9.6 s, p95 31.4 s |

**Spend:** evals $0.46, local explanations ≈ $0.03, ingest $0.0024.

**Live (2026-10-10, API `readlayer-api-00011-6sp`, web `index-DKVIFx4G.js`, deployed from `main`
after #14, API then web back to back):**

| Check | Result |
|---|---|
| New API serving | `/health` 200; GET /v1/content/{id} returns `status` |
| `scripts/live_check_m6.py` | All 4 pass: newcomer on RoDTEP gets spans 2, markers 2, pre-read 1, prompt 1; event batch applied 4, replay 0; "Not really" on SEZ → not prompted again, now a span; "RoDTEP rates" for newcomer and trader shares the restatement, Backgrounds differ. Test user deleted (204) |
| "Open here" (Wikipedia "Quantitative tightening", headless Chrome on the live site; the open request used the page's own token because Up next can't be made to offer a given URL) | Open 5.36 s (server 5.24 s), article visible **7.31 s** after the click, notes **22.5 s**, no reload. Over the 5 s target: first ingest on the new revision (deferred imports) on an instance busy with other readers' requests; warm number not measured live. Pending doc deleted, `contents/` 311, `ops/ingest` anonymous 2 |
| TTL policy on `pending_contents.expire_at` | ACTIVE |
| Demo articles re-warmed (`scripts/warm_demo.py`: ET markets preview, Guardian Polymarket/HSBC, ET RoDTEP × 3 personas, top 3 spans) | Pass 1: 24 cards, 24 verified (4 already cached); pass 2: **24/24 cache hits**, slowest 598 ms. Test user deleted |
| axe-core in the live reader | 0 violations at 1440 light, 1440 dark, 390 light |
| Console | 0 errors or warnings at 390 light and 1440 dark (paragraph card open) |

**Live spend:** one ingest, 24 warm-up cards (≈ $0.15 incl. the restatements shared across
personas), live check hits only.

---

## 15. M7 acceptance (2026-10-10, local harness on the final code, and live)

**Built.** API: consent (`consent-v1`), onboarding, calibration (8 taps, skip), consent gate,
map-node evidence, edit-by-prompt (flat schema + strict whitelist, redaction, name cap, resolver,
preview/apply/undo with exact deltas, demo session-only + reset that also restores session
settings), emulator-safety settings, transaction contention retry, rated domains in the profile.
Web: `/welcome` (with export/delete before consent), `/profile` (summary, bars with "not rated
yet", Cytoscape map + list view + node dialog, this week, analogy chips, preferences with visible
errors, edit box, data controls), onboarding gate (re-checked when the flow finishes), lazy
route chunks. Harness: `make dev-emulator`. Tests: API 489, annotator 36, web 7; profile-edit
evals `profile-edit-v3` 6/6 phrasings, 4/4 attacks. Raw harness output:
`docs/evidence/M7-harness.txt`.

| Check | Result (from `docs/evidence/M7-harness.txt`) |
|---|---|
| Two fresh accounts get different annotations and analogies on the same article | Emulator "Google" readers: software engineer vs commerce student. Guardian UK bonds **8 vs 2** spans, Guardian Polymarket/HSBC **9 vs 5**; RoDTEP card: "Analogy · software" (billing rebate / deployment fees) vs "Analogy · cricket" (touring team's kit expenses) |
| Onboarding ends on the library without a reload | After the 8th answer and after "Skip the rest": path `/`, library shown, 0 full page loads |
| Delete my data signs out; fresh sign-in starts onboarding | Confirm focuses Cancel, Escape cancels and returns focus; Delete everything → sign-in page; signing in again → `/welcome` consent step. Delete from the consent screen (before consent) also works |
| Profile page keyboard + axe | Tab walk: **31 stops for 31 tabbable controls**; list item Enter opens the node dialog, Escape returns focus to the item; axe 0 serious/critical at 1440 light, 1440 dark, 390, 320 |
| Mobile | No horizontal scroll at 320 px; list view default below 640 px; no target under 44 px in the page, node card or open preview (header items raised to 44 px after the first run flagged the 40 px icons and 21 px wordmark) |
| Knowledge map | Renders at 1440 light and dark (3 canvases, not busy); after Apply, "Options" appears in the finance list as Understands without a reload or domain switch |
| Profile edit tests | 26 tests: whitelist, cross-op fields, id-shaped names, unresolved names never stored, apply→undo exact, 11th parse → 429, >30 names refused before linking, ≤ 3 link_confirm batches, reset restores session settings |
| "I'm a backend engineer, I know options well, keep explanations short" | Preview: 1 concept known, length normal → short; settings unchanged before Apply; after Apply the "Bond sell-off" Background is **23 words vs 56** at style short. First run: a cache miss (harness log); the evidence re-run hit the cache because the first run had already made that short Background |

**Live (2026-10-10, API `readlayer-api-00012-ccv`, web `index-Dm3tU99c.js`, deployed from `main`
e7f06f0 after #16, API then web back to back):**

| Check | Result |
|---|---|
| Deep links | `/profile` and `/welcome` 200 from Hosting |
| `scripts/live_check_m7.py` | All pass: trader profile onboarding done, frame cricket; finance map 53 nodes, edges closed, 52 with recent evidence; session-only edit preview changes nothing, Apply → software + short (asserted), Undo restores both, reset 200; onboarding 403 for a demo reader; test user deleted (204). Writes: +1 on `ops/profile_edit/days/{day}`, one profile_edit call (≈ $0.001) |
| Browser pass (demo trader, headless Chrome) | Map renders at 1440 light and dark (3 canvases); list view at 390; node card opens on Enter, Escape returns focus to the item; axe 0 serious/critical ×3; 0 console errors; no target under 44 px (header re-measured) |
| Anonymous readers unaffected | Annotation id sets for 3 demo articles × 3 personas identical before and after the deploy |
| Existing signed-in users gated at consent | 1 Google user doc from before M7 (of 4 user docs); it sees the consent screen on its next visit and records nothing until then |
| Sourabh's Google check | Pending (consent → onboarding → 8 taps land on the library → profile and map → edit preview/Apply (map updates)/Undo → Delete → sign in again lands on consent) |

---

## 16. M2.2 acceptance (2026-10-10, local; decisions 32–36)

Branch `m2.2`. Full numbers and every verdict: `apps/api/evals/heldout_report.md`, `evals/report.md`
(linker suite, profile_edit), `evals/seed_report.md` (seeding dry run, production writes).

| Check | Result |
|---|---|
| Frozen-graph headline, business ≥ 75% | **Missed: 64%** (61% before) |
| Frozen-graph headline, non-business aim 60%, floor 50% | **Missed: 13%** (11% before); stop rule hit, Sourabh chose to ship and report it (decision 36) |
| After growth (production behaviour, never the headline) | business 89%, non-business 66%, all 78% |
| Grown-concept precision ≥ 90% (judged) | 26/30 (87%) first; **29/30 (97%)** after the link_confirm check and v4 scopes (not independent of the first sample) |
| Linker suite (16 frozen cases) | **Partly missed**: 13/16 → 14/16. Chancellor ×2, German chancellor and levy pass; preferential access and "Russell Indexes" (as a phrase) still null, which plan Acceptance 2 required. Russell no longer links to S&P DJI and resolves by the FTSE Russell alias |
| Variant precision (plan: ≥ 93%; BUILD_PLAN: not lower than before) | **≥ 93% not met (86%)**; not comparable with M2's sample; "not lower than before" met (83% → 86%) |
| Spot-check ≤ 2/10 wrong | **Missed: 3/10 wrong** |
| Growth: verified concept, prerequisites existing ids, acyclic, linked, caps | **Pass live** (revision 00015, demo reader pasted a BBC science article): 5 concepts grown in environment (PFAS, PFOS, forever chemicals, Phase 1/2 environmental site assessment), listed in the library (concepts_new 1), 2 grown concepts annotated for the newcomer; POST 49.6 s; reader deleted |
| `concepts.json` new version + backup, API loads it | **Pass**: seeded upload (backup = the M2.1 file), then fold → `2026-10-10-folded-5206` (backup = the seeded file); revision 00016 startup log shows the folded version, load 1.26 s |
| Taxonomy only domain list; open-domain onboarding, calibration, profile, map | Pass on the harness (seeded graph): 14 chips, axe 0, no h-scroll at 1440/390 light/dark; Health+Sports reader calibrated in health (16) and sports (8) |
| Seeding dry run | +1,874 concepts (5,201 total), no single everyday word; 42 docs / 62 demands re-link (held-out excluded); demo spans unchanged |
| Bug found on the way | Delete my data label invisible since M7 (both themes); fixed |

## 17. M7.5 acceptance (2026-10-10, emulator harness; live checks after deploy)

Evidence: `docs/evidence/M7.5-harness.txt`, screenshots in the session scratchpad (1440 and 390,
light and dark). Safety evals for the general prompts: `evals/report.md` (targets met, before and
after, non-business cases reported separately).

| # | Check | Result |
|---|---|---|
| 1 | Google reader with only Health and Sports gets articles, videos and podcasts for those topics | Pass: topics `[health, sports]`, 10 items (health 3 articles, 2 videos, 1 podcast; sports 3 articles, 1 podcast) in 4.2 s on a cold day cache, 6 searches (evidence §1) |
| 1 | Queries are only topic names; a second reader makes no new search; caps hold | Pass: property test over 14 domains; reader B 0 searches (live harness count); cap tests |
| 1 | Demo personas see the snapshot with the note | Pass: newcomer snapshot (technology 3 articles, 2 videos, 1 podcast; economics 1 article, 2 videos), 0 searches, note shown |
| 2 | Opening a pasted or feed article shows it within 5 s | Pass on the harness: 2.0, 1.0, 0.8 and 1.0 s (Read any link, same two-phase route as the feed's "Read here"); notes 63 s with growth. Live check after deploy |
| 3 | Read any link: 3 new URLs, then the cap message; other readers don't see them | Pass: 3 opened, the 4th got "The demo can analyse only a few new articles a day…"; after its notes finished, the page is listed for the paster and not for a second demo reader on the same persona (still reachable by id) |
| 4 | Habit progress matches the week's page loads | Pass: 0 of 3, read one article, 1 of 3 |
| 4 | Learning goal resolves, shows progress on the profile and the map | Pass: "understand insulin resistance" → Insulin resistance + 6 prerequisites (6 of 7 known); "Show on map" draws the 7-node chain |
| 4 | Goal boost shows in the feed's `why` | Not seen on the harness (no live item named an insulin-resistance target that day); covered offline end to end: POST a learning goal, GET /v1/feed, the item naming the target ranks first with "helps your goal: …" (`test_a_learning_goal_boosts_the_feed_item_that_names_its_target`) |
| 4 | Goals in export, gone on delete | Pass: `goals`, `ingested`, `goal_resolve_counts` in export; after DELETE /v1/me no user doc, goals, ingested or weekly docs remain |
| — | Accessibility and layout | axe: 0 serious or critical on For you (Google and demo), Goals, the map's goal view and the Read any link box, at 1440 and 390, light and dark; no horizontal scroll |
| 5 | Prompts meet the M5 targets; demo cards re-warmed live | Evals pass (before 25/25, after 24/25 good cards, G21 judge variation; all adversarial rejected; injections 10/10). Re-warm after deploy |

Found and fixed during acceptance:
- **Feed search quality:** "latest news" returned section pages. Fixes: "news this week", an article-shaped URL check, show pages only for podcasts, YouTube news explainers of 4–20 minutes from the last 30 days, relevance by label, short stem or scope words, no `exclude_domains` on feed news (with it Tavily returned 0 articles of 9), English-only titles.
- **Topics:** onboarding's 0.3 "not chosen" interest made every business domain a topic; now ≥ 0.5.
- **Rec signals:** one request per card contended on the reader's signals doc (30 s latencies, failed commits) and stalled page loads (0.5 → 31 s). Now batched to one request per 400 ms; reloads 0.5 s.
- **Copy and UI:** progress note while a learning goal resolves, library intro spacing, sign-in copy for any subject, failed thumbnails hidden.
- **Milestone review (FIX → fixes):** "Not interested" now hides the card at once and the server drops dismissed items; searches bounded to ≤ 2 per instance per (topic, format, day) with a yesterday fallback and a 10-minute backoff after a cap hit or failure; goal ids validated; end-to-end goal boost test; feed page logic tests; STATUS §4/§7/§8/§9 and the eval changelog (A06) updated.

**Live (2026-10-10 UTC, after merge #20; API revision 00017, web redeployed):**

| Check | Result |
|---|---|
| Demo snapshots | 3 `persona_feeds` docs written after a dry run: newcomer 31 items (technology 4 readable articles, economics 1), trader 32 (finance 4, business 1), policy student 27 (policy 3, politics 0); 24 search calls, no LLM. Thin topics: §5 |
| Demo cards re-warmed (`warm_demo`) | 24 requests listed by the dry run; real run pass 1: 24 verified, 0 definition-only, slowest 22.0 s; pass 2: 24 cache hits, slowest 149 ms |
| `live_check_m7_5.py` (Wikipedia "Photosynthesis", new to production) | Feed: snapshot, 10 items, Technology and Economics. Goals: 403 for a demo reader. Read any link: article visible in **6.8 s** on the first run (over the 5 s target: first ingest on the new revision, the known §5 cold-import cost) and 0.2 s when re-opened; listed for the pasting reader, not for a second demo reader. Both readers deleted (204) |
| Live axe | For you (demo) at 1440 and 390, light and dark, and the library with Read any link: 0 serious or critical, no horizontal scroll; the page shows the "prepared in advance" note. The test reader was deleted through the API (204) |
| Sourabh's Google check | Done 2026-10-11 (Sourabh): For you, Read any link and goals all work |

## 18. Design pass acceptance (2026-10-11, emulator harness; live check after deploy)

Evidence: `docs/evidence/design/acceptance.txt`, before/after screenshots in
`docs/evidence/design/{before,after}/` (1440 and 390, light and dark), audits in
`docs/evidence/design/after-audit.txt`. Plan: `docs/plans/design-pass.md` (plan-reviewer APPROVE
after three rounds).

| # | Check | Result |
|---|---|---|
| 1 | Before/after screenshots | Pass: before from the live site first (sign-in, library, For you, reader, profile; 1440 and 390, light and dark). After, from the harness: library For you, Topics and Saved, reader, profile and sign-in at all four; the open card at 1440 light and dark; the phone sheet at 390 light and dark; the map inspector at 1440 light and dark and 390 light (the profile pages at 390 include the map's list view); the recap at 1440 light |
| 2 | axe, keyboard, no horizontal scroll, 44px targets | Pass: axe 0 serious/critical on every page and state above; the map is one Tab stop with arrow keys and Enter; no sideways scroll at 390 (a top-bar overflow found and fixed); the size audit now measures inside the open card and sheet and the recap's Undo (60×44, named per concept): nothing under 44px except For you headline links, which are text links (27px, above WCAG 2.5.8's 24px) |
| 3 | Reduced motion | Pass: Margo blink and map pop off; card slide off (annotator) |
| 3b | Non-text contrast ≥ 3:1, both themes | Pass after one fix: accent-line 4.07 / 5.68, goal dashes 4.40 / 7.96, new-highlight underline over its fill 3.54 / 3.96; the heard-of map dot (fill ≈ 2:1) now carries an accent-line outline |
| 3c | Both highlight styles on a demo article | Pass: trader on the ET markets article, 4 new + 4 refresher (corpus share 8–16% per persona) |
| 4 | Flows | Pass: a note opens in the margin; "Say it simpler" returned a verified Background one band lower (can explain → understands); recap after Knew this listed Heard of → Understands and Undo showed the resulting band; no interaction → no changes; Helpful recorded one `article_helpful` event; Saved tab and export list the saved article; persona chip switches; a new Google reader's map has 48 solid nodes and 16 rings |
| 5 | Two-phase Open here and annotations unchanged | Pass: article visible in 1.5 s; the notes inked in after **88 s** on the harness (live: 20–55 s, §5). Not a regression in this branch: phase 2 is unchanged and growth was off; the harness API ran on a laptop shared with the screenshot runs and Vertex latency varies. Watch it at the live check. Tests: API 620, annotator 41, web 26 |
| 6 | Bundle | Pass: main 138.7 → 143.6 KB gzip (budget 150); Cytoscape chunk gone; For you, Saved and Profile lazy |

**Live (2026-10-11, after merge #22; API revision 00018, web deployed):** one demo reader
(trader), deleted after (204), `tools/shots/live_design.py`.

| Check | Result |
|---|---|
| Sign-in and name | "Gloss · Sign in", logo "gloss" |
| Library, profile, reader | axe 0 serious/critical, no horizontal scroll; reader on the ET markets article: 4 new + 4 refresher highlights, "8 notes for you" in the margin |
| Say it simpler | "Bourses": own band can explain (verified, cached) → understands (verified, not capped) in 19.9 s |
| Helpful | 1 `article_helpful` event in the export |
| Save | **Failed live**: the saved list stayed empty. CORS allowed GET/POST/PATCH/DELETE but not PUT (`PUT /v1/me/saved/{id}`); the harness never saw it because Vite proxies /v1. Fixed by adding PUT and a test that every method a /v1 route uses is allowed (it fails without the fix); #23, API revision 00019. Re-checked live: the PUT preflight allows PUT, and a demo reader's saved article appears in the Saved tab (reader deleted, 204) |
