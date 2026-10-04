# ReadLayer — project status and handoff

Last updated: 2026-10-05 (IST), end of M3 on branch `m3`: reader model, Firebase auth (Google +
Anonymous demo), data rights, and the **first full deploy since M0** (API + web live, §2).
Read this together with `CLAUDE.md` (rules), `docs/DESIGN.md` (spec) and `docs/BUILD_PLAN.md`
(milestone prompts). Where this file and DESIGN.md disagree, the "Deviations" section explains
why; DESIGN.md is still the target unless a deviation says otherwise.

Hackathon: Google Cloud AI Builder Cup. **Team lock Oct 11. Submission Oct 18.**

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
| M2.2 | **open issue** | #6 | Online concept growth + linker tuning, target ≥ 75% held-out linking. Not started |
| M6 slice + redesign + M6.5 | merged (squash) | #9 | See below. One commit on `main`: `M6-slice: vertical slice, redesign, recommendations` |
| M3 | done, branch `m3` (not pushed) | — | Reader model, auth, rate limits, events, export/delete, reading-profile API, rec state + ingest counter in Firestore, first full deploy. See §11 |
| M4, M5, rest of M6, M7, M8, M9 | not started | — | See "Next actions" |

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
| `apps/api` FastAPI, Python 3.12 | Local `make dev` on :8000. Cloud Run `readlayer-api`, asia-south1, min 0 / max 3, 1 vCPU / 1 GiB | **Live, M3 build**: revision `readlayer-api-00005-kmf` (same image as `-00003-xtw`), https://readlayer-api-d2sfihz3za-el.a.run.app (also https://readlayer-api-751104670850.asia-south1.run.app) |
| `apps/web` Vite + React + Firebase Auth | Local `make dev` on :5173, proxies `/v1` to :8000. Firebase Hosting | **Live**: https://readlayer-sourabh-26.web.app (Firebase web app `readlayer-web`) |
| Firebase Auth | Google + Anonymous providers | Live. Anonymous = demo mode with personas |
| `packages/annotator` | Bundled into the web app (and the extension in M8) | Final for spans; no paragraph markers / pre-read yet |
| `apps/extension` | — | MV3 scaffold only (M8) |
| Vertex AI (Gemini, Gemma MaaS, embeddings) | `global` endpoint, project `readlayer-sourabh-26` | Live, via ADC locally |
| Firestore (Native) | asia-south1 | Live |
| Cloud Storage | `gs://readlayer-sourabh-26-graph/concepts.json` (+ `concepts.prev.json`) | Live, loaded at API start |
| Secret Manager | `uid-hash-salt`, `tavily-api-key`, `youtube-api-key` (asia-south1, runtime SA has accessor) | Live |
| Tavily, YouTube Data API v3 | External, called only from the API | Keys from Secret Manager on Cloud Run; local `.env` locally |
| Firestore rules | `firestore.rules` deny all client access | Deployed |
| Firestore TTL | collection group `events`, field `expire_at` (90 days) | Enabled |

**LLM routes** (`app/llm.py` `ROUTES`; model ids come from env, never code):

| Task | Primary | Fallback | Notes |
|---|---|---|---|
| extract_demands, link_merge, concept_define, concept_prereqs, concept_wikidata, smoke | MODEL_FAST `vertex_ai/gemini-3.5-flash-lite` | MODEL_FALLBACK `vertex_ai/google/gemma-4-26b-a4b-it-maas` | |
| link_confirm | MODEL_QUALITY `vertex_ai/gemini-3.8-flash` | MODEL_FAST | 45 s timeout, batches of 10 |
| explain | MODEL_QUALITY | MODEL_FAST | Route exists; M5 not built |
| verify | MODEL_QUALITY | none | Route exists; M5 not built |
| embed | MODEL_EMBED `vertex_ai/gemini-embedding-001`, 256 dims | none | |

No LLM call exists on any reader-facing path in PR #9 (annotations, library, recommendations).
"Open here" runs the normal ingestion pipeline (extract_demands + linking).

**Firestore collections in use:** `contents/{url_hash}` (shared demand profiles),
`ops/spend/days/{date}` (LLM ledger), `ops/search/days/{date}` (search-call ledger, now with an
`anonymous` counter), `ops/ingest/days/{date}` (shared anonymous ingest count),
`rec_cache/{concept_id}__{format}` (web results, concept-level, 48 h), and per reader
`users/{uid}` with `domains`, `knows`, `events` (TTL), `weekly`, `profile_edits` (M7),
`rec_signals/{persona|default}`, `ingest_counts/{day}`. All per-user data is in
`reader_repo.USER_SUBCOLLECTIONS`, which drives both export and delete.

---

## 3. Data state (2026-10-04)

| Item | Value |
|---|---|
| Content docs in Firestore | 309 total |
| Corpus (in `data/corpus_urls.txt`) | 290 |
| Held-out (in `data/heldout_urls.txt`) | 15, never used to build the graph |
| `user_ingested` ("Open here" testing) | 2: chain.link "Singleness of money", ECB macroprudential explainer |
| Other | 2 M1 acceptance URLs (BusinessLine RoDTEP, JGU PLI evaluation), source `fetch`, in neither list |
| Publisher metadata backfilled | 306/306 dates, 273 authors, 236 standfirsts, 271 images (before the 3 docs added later) |
| Concept graph | version `2026-10-04`, 3,327 concepts (finance 1,279, economics 1,064, policy 557, business 427), 4,053 prerequisite edges, 680 Wikidata ids, acyclic |
| Held-out linking (M2.1) | 186 concept/term demands: 57% exact-name, 5% model-confirmed, **62% linked**, 38% unlinked. LINK_THRESHOLD 0.865 |
| Search cache | 87 `rec_cache` entries, 21 of them empty (no result passed the blocklist + relevance gate) |

The held-out guard (`build_concepts.corpus_sources()` refuses any corpus/held-out overlap) passes,
and `select_corpus()` now also drops `user_ingested` docs even if a URL is listed.

---

## 4. Deviations from DESIGN.md (and why)

| Deviation | Why | Resolve in |
|---|---|---|
| `link_confirm` runs on MODEL_QUALITY, not MODEL_FAST (CLAUDE.md prefers FAST) | FAST measured 89% precision, QUALITY 97% against the 95% target (M2). Recorded in CLAUDE.md and DESIGN §2/§10 | Keep |
| Placeholder scorer: prior-only p_know, hard-coded persona θ, no KNOWS edges, no `threshold_offset`, spans only (no paragraph markers, pre-read, uncertainty prompt), only graph-linked demands shown, strict first occurrence | No reader model yet (M3); the slice needed something to see | M4 |
| Personas only for **anonymous** (demo) readers, via `?persona=` (default newcomer); their hand-set θ is fixed (Elo θ updates are not stored for them, KNOWS edges are). Signed-in Google readers get no persona: θ from `users/{uid}/domains`, 0 until M7 onboarding, and a neutral `default` format prior | Decision 7; one anonymous uid can switch persona, so persona θ can't also be learned per uid | M4 seeded reader graphs |
| Google readers see the placeholder scorer at θ = 0 everywhere (no onboarding yet) | M7 not built | M4/M7 |
| Per-minute rate limits are in memory per instance (≤ 3× a limit in the worst case); daily caps are in Firestore | Cheap; money-protecting caps are exact | Keep |
| A deleted account's still-valid ID token (≤ 1 h) is refused only on the instance that ran the delete | No per-request revocation check (an extra Auth call per request) | M9 if needed |
| Web search queries are `label + graph domain + format suffix`, not label + suffix only | Bare labels were ambiguous ("separation principle" returned a marine-engineering video). Domain is concept data, never reader data | Accepted as the rule (decision 4, DESIGN §16.3) |
| Web results must name the concept (relevance gate); results normalized and cached per (concept, format) with a cache version | Off-topic podcasts and stale thumbnails in the first live run | Keep |
| Up next format mix: preferred format 3 slots, then 2 and 1 by affinity; spare slots pass to the next format; at least one library and one web item when both exist | 2-per-format forced 2/2/2 for every reader, hiding preferences | Keep |
| Recommendations (M6.5), GET content routes, `/v1/recs/*` and publisher metadata were built ahead of the spec | Needed for the slice | Now documented: DESIGN §3, §4, §8, §16 (decision 9) |
| Publisher lead images are hotlinked with `referrerpolicy=no-referrer`, typographic tile on error | Fast demo; no image proxy | Keep (decision 3) |
| Content `source` adds `user_ingested`; build and held-out scripts exclude it | Reader-opened pages must never become corpus or held-out data | Keep |
| Annotator card shows the concept definition + prerequisites, not the two-part verified explanation; no "This is wrong" button. Card events (explain_opened, knew_this, explain_helpful) now go to POST /v1/events (5 s batches + on hide); paragraph_dwell / text_searched not emitted yet | M5 (explanations), rest of M6 (dwell, text search) | M5 / M6 rest |
| Annotation response carries `definition`, `domain`, `prerequisites`, `debug` beyond the §8 shape | The card needs them until explanations exist | Revisit in M5 |

---

## 5. Known issues and tech debt

| Severity | Issue |
|---|---|
| **High** | Local `LLM_DAILY_BUDGET_USD` is **25** (raised for M2 builds); you are setting it back to 8 (decision 2). Cloud Run uses 8 (`deploy.env.yaml`) |
| **High** | **Cold start ≈ 22 s** on Cloud Run (min instances 0): a reader arriving after scale-to-zero waits that long for the first response. Before judging: startup CPU boost, lazier LiteLLM/spaCy imports, min instances 1 (§11) |
| Medium | **M9: Firebase App Check (reCAPTCHA Enterprise)** to stop scripted anonymous sign-ups. Shared anonymous caps bound the cost today (30 new URLs/day, 100 search calls/day), but a script can still mint accounts and burn those shared allowances for everyone |
| Medium | **M9: scheduled cleanup of anonymous users with no activity for 30 days** (Auth user + `users/{uid}`). "End demo" deletes on request; abandoned demo sessions pile up until then |
| Medium | `concepts.json` in GCS lacks `doc_freq` until `uv run python -m scripts.add_doc_freq --upload` runs (the auto-mode classifier denied it; your call). Local copy is patched. Without it a new reader's knowledge map seeds from arbitrary concepts instead of the most frequent |
| Medium | "Open here" takes 24–55 s for a new article (fetch + extract_demands + linking incl. link_confirm). UI says "up to a minute" and shows elapsed time. Two-phase loading in the rest of M6 (decision 6) |
| Medium | Placeholder scorer and invented persona/format priors drive everything a reader sees |
| Medium | Held-out linking 62% (target ≥ 75%), Chancellor→Treasury Secretary and levy over-generalisation (issue #6) |
| Medium | No explanations yet (M5): cards show only the graph definition |
| Low | Publisher images set third-party cookies (Lighthouse best-practices 96 on the library). Broken hotlinks fall back to the typographic tile everywhere |
| Low | Web result quality varies (some generic podcasts, an exam-prep video); 21 of 87 cache entries empty |
| Low | Headlines keep publisher SEO suffixes (" \| Stock Market News"); we don't alter publisher text |
| Low | In-process catalog cache: docs ingested by another process need an API restart to appear (Open here appends directly) |
| Low | `rec_signals` keeps `seen` and `shown_counts` unbounded (served items and event ids are capped); a very heavy reader could approach the 1 MiB doc limit after thousands of items |
| Low | `rec_shown` relies on IntersectionObserver, which browsers pause in background tabs (seen in automated testing; real readers have the tab in front) |
| Low | Web build is 128 KB gzipped JS now that Firebase Auth is in (budget 150 KB) |
| Low | StarletteDeprecationWarning (httpx TestClient) in pytest output |

---

## 6. Config (names only, never values)

| Name | Purpose | Local | Cloud Run (currently deployed) | Secret Manager |
|---|---|---|---|---|
| ENV, LOG_LEVEL | runtime mode, logging | `.env` | yes | — |
| GCP_PROJECT, VERTEX_LOCATION | project, Vertex endpoint | `.env` | yes | — |
| MODEL_FAST, MODEL_QUALITY, MODEL_FALLBACK | LLM routes | `.env` | yes | — |
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
| M3, M4 (no LLM on the scoring path) | ~$0 |
| M5 explanations + verifier + 40-case suite + 10 injection cases | $2–5 |
| M2.2 online growth (one batched concept_define per article) + held-out re-runs | $2–4 |
| M7 profile edits, onboarding | < $1 |
| M8 extension ingestion (~$0.0075 per new article) | < $2 |
| M9 gold-set evals (30 articles × 2 personas) and demo pre-ingest | $3–6 |
| Hosting after submission: Cloud Run min-instances 1 during judging (Oct 19 – Nov 6) | ~$15–25 |
| **Total remaining** | **≈ $25–45 of the $300 credit** |

Tavily cost depends on the plan in use (check the free monthly credit before M9); YouTube
quota is free within the daily buckets.

---

## 8. Guardrails in force

- **LLM budget:** `llm.py` refuses non-cached calls past `LLM_DAILY_BUDGET_USD` = 8. It is raised
  only for a specific run, with the reason recorded (here or in the PR), and set back after
  (decision 2). Spend ledger in `ops/spend/days`.
- **Search cap:** `SEARCH_DAILY_CAP` 300 calls/day across providers, `YOUTUBE_SEARCH_DAILY_CAP`
  90 searches/day; calls are reserved under a lock before they're made; past the cap the API
  serves cached (even stale) results and makes no call.
- **Ingest cap:** 20 new URLs per reader per day (3 for anonymous, 30 shared across all
  anonymous readers), on both POST /v1/content and "Open here", reserved in a Firestore
  transaction before ingesting and refunded on failure. Known URLs are free.
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

| When | Action |
|---|---|
| Oct 5 | Set `LLM_DAILY_BUDGET_USD` back to 8 in `apps/api/.env` (you, by hand) |
| Oct 5 | Review and merge branch `m3` (commit `M3: …`; push and PR when you say). Optionally run `scripts.add_doc_freq --upload` |
| Oct 7–8 | **M4** real gap scorer: replace `app/scoring/placeholder.py`; personas become seeded reader graphs; worked-example test; p95 < 150 ms |
| Oct 8–9 | **M5** explanations + verifier + safety evals; card shows Background / What the author is saying |
| Oct 9 | **Rest of M6:** two-phase loading for "Open here", "This is wrong" button, paragraph markers, pre-read card, event batching to /v1/events |
| Oct 9–10 | **M2.2** (issue #6): online concept growth, jurisdiction, link_confirm strictness; held-out set grows to 30; target ≥ 75% linked |
| Oct 10–11 | **M7** onboarding, consent, calibration, reading profile page, profile edits. **Team lock Oct 11** (gate: if M6–M7 aren't solid, skip M8) |
| Oct 12–14 | **M8** Chrome extension with privacy guards (only if the gate passed) |
| Oct 15–17 | **M9** evals, hardening, WIF deploy, dashboard, demo personas, README, video, deck |
| **Oct 18** | **Submit** |

---

## 10. Decisions (all decided 2026-10-04)

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

No decisions are open.

---

## 11. M3 acceptance (verified 2026-10-04/05)

**Live URLs:** web https://readlayer-sourabh-26.web.app · API
https://readlayer-api-d2sfihz3za-el.a.run.app (revision `readlayer-api-00005-kmf`).

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

**Cold start.** From Cloud Run's "Starting new instance" to ready: **≈ 22 s** (23.6 s and 21.9 s
on two deploys). About 21 s of it comes before uvicorn starts (image start + Python imports:
LiteLLM, Google SDKs, spaCy library) on 1 vCPU; app startup itself is 0.55 s, of which the GCS
graph load is 0.55 s. Warm `/health` 0.05–0.12 s; first library list per instance ≈ 2.1 s (loads
309 docs), then 0.15–0.3 s. **spaCy model load not measured yet** (it loads on the first new
article; the budget refusal stopped that run) — rerun "Open here" on a new URL after 00:00 UTC
and read the `spacy loaded` log line. Options before judging: Cloud Run startup CPU boost,
lazier imports of LiteLLM/spaCy, and min instances 1 (already planned for Oct 19 – Nov 6).

**M3 spend:** $0 LLM (the one ingest attempt was refused). Search: 36 calls, all anonymous.
