# ReadLayer — build plan for Claude Code

One milestone per Claude Code session. For each one:
1. Start a fresh session (`/clear` between milestones keeps context lean).
2. Switch to plan mode (Shift+Tab, or prefix the prompt with `/plan`), paste the prompt.
3. Read the plan. Push back on anything that drifts from `CLAUDE.md` or `docs/DESIGN.md`.
4. Approve, let it build, then make it run the acceptance checks itself.
5. Commit: `M<n>: <summary>`.

Dates assume the 2026-10-18 submission deadline. Security, privacy and evaluation work is
folded into the milestones it belongs to, not saved for the end.

---

## M0 — Scaffold, LLM layer, CI, skeleton deploy (Oct 4)
**Prompt**
> Read CLAUDE.md and docs/DESIGN.md sections 1, 8, 10 and 13. Scaffold the monorepo exactly as
> the Layout section describes: pnpm workspace (apps/web, apps/extension, packages/annotator) and
> a uv-managed Python project in apps/api. Create `app/main.py` with `/healthz`, `app/config.py`
> (pydantic-settings), and `app/llm.py` per DESIGN §10: LiteLLM SDK backend, task→route table,
> fallback chain, Pydantic structured output with local re-validation, retries, per-call cost
> logging, daily budget guard stored in Firestore, prompt files under `app/prompts/` with a
> version header. Look up the current Gemini model IDs on Vertex AI and set defaults in
> `.env.example` for MODEL_FAST and MODEL_QUALITY. Then check whether Gemma is reachable as a
> pay-per-token Vertex Model-as-a-Service model from LiteLLM (directly or through Vertex's
> OpenAI-compatible endpoint); if yes set MODEL_FALLBACK, if not leave it empty and tell me.
> Add JSON structured logging with request_id and uid_hash, a Dockerfile for Cloud Run,
> `firebase.json`, a Makefile (`dev-api`, `test`, `deploy-api`, `deploy-web`), and a GitHub
> Actions workflow running ruff, pytest and TS typecheck on PRs. Add a smoke script that calls
> `llm.run` once and prints tokens and cost.

**Acceptance**
- `uv run pytest -q` passes, including a test that the budget guard refuses calls past the limit
  (mock the spend store).
- Smoke script returns a schema-valid response and logs cost.
- Forcing the primary model to fail (bad model id) falls back and still returns a valid result.
- `make deploy-api` and `make deploy-web` succeed; CI is green on a test PR.

**You do by hand first:** create the GCP project; enable Vertex AI, Cloud Run, Firestore
(Native mode), Cloud Storage, Secret Manager, Firebase; set billing alerts at $50 / $100 / $200;
`gcloud auth application-default login`; create the GitHub repo.

---

## M1 — Safe ingestion and demand profiles (Oct 5)
**Prompt**
> Implement `app/ingest/` per docs/DESIGN.md sections 3 and 11.2. First `safe_fetch.py`: scheme
> and port allowlist, DNS resolution with private/loopback/link-local/metadata IP rejection
> (IPv4 and IPv6), re-check on every redirect (max 3), pinned IP, 10 s timeout, 3 MB cap,
> HTML-only, robots.txt check. Unit-test it with SSRF cases (127.0.0.1, 169.254.169.254, [::1],
> a hostname resolving to 10.x, a redirect to an internal IP, a decimal-encoded IP). Then
> extraction with trafilatura, stable paragraph ids, zipf (wordfreq) and structure features
> (spaCy en_core_web_sm). Demand extraction via `llm.run("extract_demands", ...)`: article text
> goes inside clear delimiters and the prompt states that content is data, not instructions.
> Verify every anchor's `exact` occurs in its paragraph and compute prefix/suffix from the real
> text. Store via `app/store/`. Expose POST /v1/content for both input shapes in DESIGN §8.
> Tests use a saved HTML fixture (no network).

**Acceptance**
- All SSRF test cases are rejected; normal news URLs pass.
- Posting 3 real business-news URLs creates `contents/{url_hash}` docs with plausible demands.
- Re-posting the same URL makes no LLM call (cache hit, logged).

---

## M2 — Corpus and concept graph (Oct 6)
**Prompt**
> Write `scripts/ingest_corpus.py` (reads `data/corpus_urls.txt`, ingests with concurrency 4,
> resumable) and `scripts/build_concepts.py` per docs/DESIGN.md section 2: collect concepts from
> all demand profiles, embed, dedupe (cosine ≥ 0.88 + LLM merge check), add Wikidata ids where a
> confident match exists, LLM definitions and base_difficulty, prerequisite pass (≤ 3, existing
> concepts only, no cycles, verified with networkx). Upload concepts.json to GCS. Implement
> `app/graph/` to load it at startup and expose lookup, prerequisites and entity linking.
> Re-link existing demand profiles to final concept ids. Print a summary report with total LLM
> cost for the build.

**Acceptance**
- 200–300 articles ingested; zero prerequisite cycles.
- Report shows the 20 most frequent concepts and sample prerequisite chains that make sense.
- Spot-check 10 entity links by hand; fix thresholds if more than 2 are wrong.

**You do by hand:** put 200–300 business/economy article URLs in `data/corpus_urls.txt`.

---

## M3 — Reader model, auth and data rights (Oct 7)
**Prompt**
> Implement `app/reader/` as pure functions per docs/DESIGN.md section 4: IRT prior, Beta
> init/update/forgetting, bands, evidence weights, Elo θ update. Then `app/store/reader_repo.py`
> for the Firestore layout. Wire Firebase ID-token auth as a FastAPI dependency and per-uid rate
> limits from DESIGN §11.5. Expose POST /v1/events (idempotent by event id), GET /v1/me/graph,
> PATCH /v1/me/graph/{concept_id}, GET /v1/me/export and DELETE /v1/me per DESIGN §11.4. Add
> Firestore security rules that deny all client access, and a TTL policy on raw events (90 days).
> Unit-test every formula, including forgetting after 90 days halving the distance to the prior.
> Then the reading-profile API per DESIGN §15.2: band/band_prev/band_changed_at on KNOWS
> updates, `users/{uid}/weekly/{iso_week}` stats, `doc_freq` in concepts.json, GET /v1/me/profile
> (summary from the deterministic template in §15.1, no LLM call), GET /v1/me/graph?domain=X
> (≤ 60-node subgraph: most relevant concepts plus prerequisite closure; `q` search),
> PATCH /v1/me/settings, and `learning_paused` honoured in POST /v1/events.
> Auth covers Google sign-in and **Firebase Anonymous sign-in**: the demo personas (newcomer,
> trader, policy_student) become a demo mode served through anonymous accounts, each carrying
> its persona until M4 replaces hand-set θ with seeded reader graphs. Remove `DEV_AUTH_BYPASS`
> from every path that a deployed build can reach (keep the K_SERVICE refusal and its test).
> Move the M6.5 recommendation state (format affinity, relation dismissals, seen items, event
> ids) and the "Open here" daily ingest counter out of API memory into Firestore under
> `users/{uid}/rec_signals` and `users/{uid}/ingest_counts`, covered by GET /v1/me/export and
> DELETE /v1/me. Put the auth dependency and the per-user daily cap (INGEST_DAILY_CAP, default
> 20) on POST /v1/content and POST /v1/recs/open; POST /v1/content stays disabled in prod until
> both are in place. Finish with the **first full deploy since M0**: API to Cloud Run (env from
> `deploy.env.yaml`, UID_HASH_SALT, TAVILY_API_KEY and YOUTUBE_API_KEY from Secret Manager, CORS
> for the web origin only, min 0 / max 3 instances) and web to Firebase Hosting, then verify live.

**Acceptance**
- `reader/` fully covered by tests; replaying an event twice changes nothing the second time.
- Export returns every user document (including weekly stats and settings); delete leaves no
  document under `users/{uid}` and removes the Auth user (integration test against the Firestore
  emulator).
- Logs contain `uid_hash` and never an email or token.
- Summary template: same inputs give the same text; a test asserts no LLM call on the profile path.
- GET /v1/me/graph?domain=X never returns more than 60 nodes, every edge's endpoints are in the
  node set, and the subgraph is acyclic.
- With `learning_paused` set, POST /v1/events returns `applied: false` and changes no document;
  PATCH /v1/me/graph still applies.
- An anonymous demo session for each persona gets the same annotations and recommendations as
  the local slice did; rec signals and ingest counts survive an API restart, appear in export
  and are gone after delete.
- POST /v1/content and POST /v1/recs/open return 401 without a token and 429 on the 21st new URL
  of the day for one user.
- Live deploy verified: `/health` 200; the web app on Hosting signs in anonymously, opens a
  corpus article with annotations and Up next (web items present, so the Secret Manager keys
  work); no Tavily or YouTube key appears in the web bundle, the browser or the logs; a request
  from another origin is refused by CORS; the deployed revision refuses to start with
  `DEV_AUTH_BYPASS=true` set.

**You do by hand:** enable the Anonymous and Google providers in Firebase Authentication;
approve the Secret Manager and deploy commands when asked.

---

## M4 — Gap scorer and annotation budget (Oct 8)
**Prompt**
> Implement `app/scoring/` per docs/DESIGN.md sections 5 and 6 as pure functions, then
> GET /v1/content/{id}/annotations. Reproduce the worked example from the design doc as a unit
> test. Add the density dial, threshold_offset, the pre-read prerequisite path and the
> uncertainty prompt rule. Log p95 latency.

**Acceptance**
- Worked-example test passes; same reader + article always returns identical annotations.
- p95 under 150 ms locally for a 1,200-word article (excluding cold start).

---

## M5 — Explanations, verifier, safety evals (Oct 9)
**Prompt**
> Implement `app/explain/` per docs/DESIGN.md section 7: generation (inputs restricted to span,
> paragraph, concept definition, band, THINKS_IN domain; no user identifiers), deterministic
> checks, LLM entailment judge, regenerate-once, fallback to definition, Firestore cache storing
> model and prompt_version. Expose POST /v1/explain. Create `evals/` with: 15 adversarial
> faithfulness cases (dropped hedge, dropped attribution, changed number, flipped negation,
> opinion stated as fact), 10 good cases, and 10 prompt-injection articles per DESIGN §12.3.
> `uv run python -m evals.run --suite safety` prints pass/fail and cost.

**Acceptance**
- All adversarial faithfulness cases rejected; good cases accepted.
- All injection cases produce schema-valid output that ignores the planted instructions.
- Cache hit on second request (no LLM call, logged).

---

## M6 — Annotator library and web reader (Oct 10)
**Prompt**
> Build `packages/annotator` per docs/DESIGN.md section 9: anchor resolution (exact+prefix+suffix,
> whitespace-normalized fallback), dotted underlines, hover/tap cards with Knew this / Helpful /
> This is wrong, paragraph margin markers, pre-read card, event batching. Cards must be keyboard
> reachable with proper ARIA roles. No framework dependency; ship types. Then build `apps/web`:
> Firebase Google sign-in, paste-a-link page, reader view that mounts the annotator. Use the
> frontend-design approach: calm, typographic, reading-first; annotations quieter than the text.

**Acceptance**
- Paste a corpus URL → annotated article in under 3 s warm.
- "Knew this" removes the annotation on reload and moves the concept's band in /v1/me/graph.
- All card actions work with keyboard only.

---

## M7 — Onboarding, consent, calibration, reading profile page (Oct 11)
**Prompt**
> Implement /v1/onboarding and /v1/calibration/next|answer per docs/DESIGN.md sections 4 and 8.
> In apps/web: a consent screen (what we collect, why, export/delete links) per DESIGN §11.4,
> then a 90-second onboarding flow (field → interests → domain comfort → 8 calibration taps →
> optional liked links). Then the reading profile page per DESIGN §15.1: summary card, ability vs
> interest bars, per-domain knowledge map (Cytoscape.js + dagre, dynamically imported, ≤ 60
> nodes, search, node card with last 3 evidence items and I know this / I don't, plus a
> keyboard-navigable list view of the same subgraph), this week's band changes and the
> annotations-per-1,000-words trend, editable THINKS_IN domains, Export / Delete / Pause learning.
> Then "Edit profile with a prompt" per DESIGN §15.3: `profile_edit` route on MODEL_FAST with a
> versioned prompt file, whitelisted ops only, concept names resolved through the graph linker,
> preview diff before Apply, profile_edit events with undo, AI-processing notice, no user id in
> the prompt, 10 edits/day/user. Add `explanation_style` to the explain prompt inputs and the
> explanation cache key.

**Acceptance**
- Two fresh accounts (software engineer vs commerce student) get visibly different annotations
  and analogies on the same article.
- Delete my data signs the user out and a fresh sign-in starts onboarding again.
- Profile page is fully keyboard accessible: every control reachable and operable with Tab,
  Enter and Escape; the knowledge map is usable through its list view; node card is a dialog
  that returns focus; no serious or critical axe violations.
- Readable on mobile: no horizontal scroll at 320 px; the map falls back to the list view below
  640 px; tap targets ≥ 44 px.
- Profile edit tests pass: off-schema or malicious model output rejected as a whole, unknown
  concept names reported as "couldn't find", apply then undo restores α, β, θ and settings
  exactly, the 11th parse request in a day returns 429.
- "I'm a backend engineer, I know options well, keep explanations short" previews and applies the
  expected ops; nothing changes before Apply; the next explanation is shorter and is a cache
  miss for the new style.

**Gate:** if M6–M7 are not solid by end of Oct 11, skip M8 and spend Oct 12–14 on polish.

---

## M8 — Chrome extension with privacy guards (Oct 12–14, only if the gate passed)
**Prompt**
> Build `apps/extension` (MV3) per docs/DESIGN.md sections 9 and 11.3. Activation only on toolbar
> click or allowlisted news domains; never on pages with password fields, card inputs, or
> mail/bank/intranet URL patterns. Run Readability.js on a DOM clone, send only the extracted
> title and paragraphs (never raw HTML, comments or form fields) after client-side redaction of
> emails, phones, Luhn-valid digit runs and Aadhaar/PAN-like patterns. Server side, add the
> Presidio backstop to the `{url, title, paragraphs}` path of /v1/content. Mount
> `packages/annotator` against the live DOM. Auth via the web app's /extension-connect page
> using `externally_connectable`; keep tokens in memory or session storage only. Minimal
> permissions (`activeTab`, `scripting`, `storage`, host permissions only for the allowlist).

**Acceptance**
- Works on 3 news sites without site-specific code.
- Does nothing on a Gmail tab, a bank login page and a page with a password field (manual test).
- A test page with an email and a phone number in the article body arrives server-side redacted.

---

## M9 — Evaluation, hardening, demo, submission (Oct 15–17)
**Prompt**
> Build the quality evals per docs/DESIGN.md §12.1 and §12.4: load `evals/gold/*.json` (spans a
> human marked per persona), compute annotation precision/recall per persona at balanced density,
> cost per article and per explanation, cache hit rate and p95 latency; write `evals/report.md`.
> Set Cloud Run max instances 3 and finish rate limits. Switch CI deploy to Workload Identity
> Federation. Create a Cloud Monitoring dashboard (requests, errors, p95, daily LLM spend). Write
> `scripts/seed_personas.py` for the two demo accounts, pre-ingest the demo articles, and write
> README.md covering architecture, setup, how Gemini (and Gemma, if used) is used at each stage,
> security and privacy measures, and the eval results.

**You do by hand:** label the gold set (30 articles × 2 personas, split with your teammate,
start this on Oct 12); record the 3-minute video (same article, two personas side by side; the
verifier catching a bad explanation; the graph page showing learning); build the PDF deck with
the eval numbers; set Cloud Run min instances to 1 for Oct 19 – Nov 6; submit on Oct 17.
