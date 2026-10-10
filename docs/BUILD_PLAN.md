# ReadLayer — build plan for Claude Code

One milestone per Claude Code session. For each one:
1. Start a fresh session (`/clear` between milestones keeps context lean).
2. Switch to plan mode (Shift+Tab, or prefix the prompt with `/plan`), paste the prompt.
3. Read the plan. Push back on anything that drifts from `CLAUDE.md` or `docs/DESIGN.md`.
4. Approve, let it build, then make it run the acceptance checks itself.
5. Commit: `M<n>: <summary>`.

Dates assume the 2026-10-18 submission deadline; we submit on Oct 17. Security, privacy and
evaluation work is folded into the milestones it belongs to, not saved for the end.

## Schedule (re-planned 2026-10-10)

M0–M4 and the M6 slice are merged and live. The rest:

| Date | Work |
|---|---|
| Oct 10 | **M5** explanations, verifier, safety evals |
| Oct 11 | **Rest of M6**: show paragraph markers, the pre-read card and "Know this?" prompts; two-phase "Open here"; complete event batching |
| Oct 12–13 | **M7**: profile page (summary, domain bars, knowledge-map graph and list view, corrections); Google onboarding with consent and calibration; edit-by-prompt. All required (decision 27) |
| Oct 10–11 | **M2.2 (full scope, decision 32, extended with open domains, decision 33)**: fixed 14-domain taxonomy, online concept growth into it, jurisdiction in `link_confirm`, linker strictness, Russell mislink, 30-article held-out set with non-business articles, ≥ 75% linked, linking per domain |
| Oct 12–13 | **M7.5** (decision 33): "For you" feed for Google readers, "Read any link" box, reading goals |
| Oct 13 | **Design pass** (decision 39): Medium-style reading product, right after M7.5 is merged and deployed |
| Oct 14 | **M8-local**: unpacked Chrome extension (Developer mode), activeTab only (plan approved, paused on branch `m8`) |
| Oct 15 | **M9** hardening and evals |
| Oct 16 | Demo seeding, README refresh, video, deck |
| Oct 17 | **Submit** |

**Order (Sourabh, 2026-10-10, decisions 33 and 39):** M2.2 → M7.5 → Design pass → M8-local → M9. ReadLayer is not a
business-only reader; demo personas stay curated as they are, open domains are for signed-in
(Google) readers.

**If late:** stop and ask Sourabh what to cut (decisions 27 and 33); nothing is cut automatically.

**Post-hackathon:** Chrome Web Store release of the extension.

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

## M5 — Explanations, verifier, safety evals (Oct 10)
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

## M6 — Annotator library and web reader (slice merged in #9; rest Oct 11)
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

### Rest of M6 (Oct 11)
**Prompt**
> The API already returns paragraph markers, the pre-read path and the "Know this?" prompt
> (DESIGN §6). Show them in `packages/annotator` and `apps/web`: a quiet margin marker per
> paragraph item, a pre-read card above the article (steps most basic first, each linking to its
> corpus explainer or showing the definition), and the prompt as an inline "Know this?" with
> Yes / Not really that sends PATCH /v1/me/graph. Make "Open here" two-phase: return the
> article as soon as it is fetched and extracted, then annotations when demand extraction and
> linking finish (UI shows the article first, notes ink in after). Complete event batching:
> emit `paragraph_dwell` (IntersectionObserver), `text_searched` and `annotation_dismissed`
> alongside the existing card events, 5 s batches and on visibilitychange.

> Carried over from the M5 review (decided 2026-10-10, for the Oct 12 M6 session):
> (1) generate "What the author is saying" once per (span, style) and personalise only Background:
> the restatement gets its own cache key and one verifier pass per span, the Background its own
> per-reader key; (2) label the Helpful button with text instead of a bare thumb icon.

**Acceptance**
- Markers, pre-read card and prompt render for a persona that triggers them, keyboard reachable,
  no serious axe violations; answering the prompt changes the next load.
- "Open here" on a new URL shows the article before its notes; notes arrive without a reload.
- Events from one reading session arrive in batches and are applied once (replay-safe).

---

## M7 — Onboarding, consent, calibration, reading profile page (Oct 12–13)
**Scope (decided 2026-10-10, decision 27): everything below is required.** The profile page with
the summary card, ability vs interest bars per domain, the Cytoscape knowledge-map graph with its
keyboard-navigable list view of the reader's concepts and "I know this" / "I don't" corrections,
editable THINKS_IN, Export / Delete / Pause; Google onboarding with the consent screen and
calibration; and edit-by-prompt (§15.3). Nothing is cut without asking Sourabh first.

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


---

## Design pass — Medium-style reading product (decision 39; after M7.5, before M8)
**Scope (Sourabh, 2026-10-10): everything below is required.** Same plan-reviewer and
milestone-reviewer loop, plus before/after screenshots at desktop, mobile and dark in
`docs/AUTOPILOT_LOG.md`. Inspired by Medium's layout and typography; no Medium branding, logo or
copied assets.

1. **Tokens.** White background (dark mode near-black), near-black ink, one accent, real contrast.
   Reading serif in the Charter style (Source Serif 4 or a similar free font) at 20–21px for the
   article body; a clean sans for UI at ≥ 14px. No light-grey 12px text for anything a reader
   needs.
2. **Library becomes a feed.** Tabs "For you · Topics · Saved"; single-column rows (source and
   favicon line, big bold title, one-line grey subtitle, thumbnail right, read time, quiet save
   and not-interested icon buttons, "N new concepts" as a readable tag, not a faint pill). Right
   sidebar on desktop: recommended topic chips, reading-goal progress, "Read any link". Fix the
   stale tagline.
3. **Reader.** 680px column, large bold title, byline with source, a sticky slim action bar
   (Helpful, save, share link, notes density). Annotations feel like Medium highlights: soft
   underline, the card slides from the margin on desktop, a bottom sheet on mobile. Clear hover
   and focus states, small purposeful motion (respect prefers-reduced-motion).
4. **Profile.** Lead with a readable summary; domain cards instead of thin bars (level, interest,
   trend). **Knowledge map redesign:**
   - a force/radial layout clustered by domain;
   - known concepts solid, and "next to learn" neighbours from the global graph as faint outline
     nodes, so a new reader's map is never empty;
   - node size by salience, colour by band;
   - an overview of all domains first, then drill in;
   - new nodes animate in.
   Keep the accessible list view.
5. **Keep everything that works:** accessibility (axe 0, keyboard, 44px targets), the bundle
   budget, two-phase loading, annotation behaviour.

**Additions (Sourabh, 2026-10-10 22:06, decision 40; also required):**

6. **Name: Gloss.** Rename the product to "Gloss" for display only: logo, page titles, meta tags,
   copy, README and deck. Firebase project, URLs, repo name and internal ids stay as they are.
7. **Visual target: `docs/design/mockup.html`.** Open it in headless Chrome (tabs: Feed, Reader,
   Profile and map, Logo and Margo; light and dark). Match its layout, type (Schibsted Grotesk
   for UI and headlines, Source Serif 4 for reading), tokens and the knowledge-map style. It is a
   target, not code to copy: rebuild it in our components with real data, accessibility and the
   bundle budget. Commit the mockup with the Design pass branch.
8. **Mascot: Margo.** Use the `margo()` SVG from the mockup (one ink outline, one teal swipe; moods
   idle, thinking, happy, oops, plus the simplified 16px mark). Where it appears: logo, favicon,
   extension icon, the reader margin header, the notes-loading state, the end-of-article recap,
   empty and error states. Never inside article text, never on every note card, never animated
   while the reader reads (an occasional blink when idle is fine; none under
   prefers-reduced-motion). Decorative SVGs are aria-hidden.
9. **Reader details from the mockup** (size these in the plan; some need API work):
   - "Before you read" as a path of steps (known steps ticked, the article's key idea last; a step
     opens its definition or links to an explainer);
   - two highlight styles: ideas new to the reader vs quick refreshers;
   - the margin shows "N notes for you" as a mini contents list until a note opens; the note card
     opens level with the highlighted line, with a connector;
   - the card shows how it was pitched (level meter and one line), "Builds on" (prerequisites),
     and "Say it simpler" / "Go deeper", which request the explanation one band lower or higher
     through the normal verified path (cached by band, counted against the explain caps);
   - "What the author is saying" set as a quote;
   - **"What this article changed"** at the end: the reader's band changes from this page view
     (with undo, through the existing correction route), plus read-next and watch-next items that
     teach what the reader said they didn't know. Margo (happy) heads it.
10. **Mobile:** note card as a bottom sheet; paragraph markers only where a paragraph note exists.

## M8-local — Chrome extension, unpacked (Oct 14)
Replaces the original M8. Loaded unpacked via chrome://extensions → Developer mode; not
published to the Chrome Web Store (a post-hackathon item).

**Prompt**
> Build `apps/extension` (MV3) per docs/DESIGN.md sections 9 and 11.3, with these limits.
> Permissions `activeTab`, `scripting` and `storage` only: no host permissions and no automatic
> injection; it runs only when the reader clicks the toolbar button. On click, still refuse on
> pages with password fields, card inputs, or mail/bank/intranet URL patterns. Run Readability.js
> on a DOM clone; send only the extracted title and paragraphs (never raw HTML, comments or form
> fields) after client-side redaction of emails, phones, Luhn-valid digit runs and
> Aadhaar/PAN-like patterns. Server side, add the Presidio backstop to the
> `{url, title, paragraphs}` path of /v1/content. Mount `packages/annotator` on the live page.
> Auth through the web app's "Connect extension" page using `externally_connectable`, for both
> anonymous (demo) and Google readers; tokens in memory or `storage.session` only. A popup shows
> sign-in state, the persona (demo readers), density and a link to the profile page. Add
> "Install the extension locally" steps to README.md.

**Acceptance**
- Works on 3 news sites without site-specific code, for a demo reader and a Google reader.
- Does nothing until clicked; on click, refuses on a Gmail tab, a bank login page and a page
  with a password field (manual test).
- A test page with an email and a phone number in the article body arrives server-side redacted.
- `manifest.json` lists no host permissions and no content scripts.

---

## M2.2 — Open domains, online concept growth and linker quality (full scope, issue #6; Oct 10–11)
**Scope (decided 2026-10-10, decisions 32 and 33): everything below is required; nothing is
trimmed.**

**Open domains (decision 33).** Replace the 4 fixed domains with one fixed taxonomy of 14
top-level domains: economics, finance, business, policy, politics, law, technology, science,
health, environment, sports, culture, education, society. The old four keep their ids, so the
existing graph, persona templates and reader θ stay valid. Online concept growth assigns every
new concept to a taxonomy domain (`concept_define` is constrained to the list). Onboarding
interests, comfort and calibration offer the whole taxonomy; calibration only draws from domains
that have enough concepts. Demo personas are unchanged.

**Seeding and targets (decision 34).** Each new domain is seeded from Wikipedia glossaries
(Glossary of medicine, computer science, cricket terms, association football, biology, law, …)
fetched through `safe_fetch` and parsed deterministically from their definition lists, then put
through the normal dedupe / `concept_define` / keep / prerequisites pipeline. Concept counts and
production writes go to Sourabh before anything is written. The held-out set (30 articles)
includes non-business articles; per domain the report gives (1) the frozen-graph link rate, the
headline: business ≥ 75%, non-business aim 60%, under 50% → stop and tell Sourabh; (2) the
after-growth link rate, labelled production behaviour; (3) precision on a judged sample of grown
concepts, ≥ 90%. Links to concepts grown from the same article never count in the headline.

**Prompt**
> Read docs/DESIGN.md §2 and §3 and issue #6. (1) **Online concept growth:** when a newly ingested
> article (POST /v1/content, "Open here", the extension) has concept demands that don't link,
> propose new concepts for them in one batched `concept_define` call per article (definition,
> domain, base_difficulty, ≤ 3 prerequisites chosen from existing concepts only, no cycles,
> checked with networkx), dedupe against the graph (cosine ≥ DEDUPE_THRESHOLD + `link_merge`),
> embed, and add them to the live graph and to `concepts.json` in Cloud Storage with a version
> bump and a backup of the previous file; link the article's demands to them. Cap new concepts
> per article and per day, count them against the LLM budget, and never grow from `user_ingested`
> or held-out text without the same checks. (2) **Jurisdiction:** add `jurisdiction` (country or
> "global") to concepts and use it in `link_confirm` so a UK "Chancellor" never links to the US
> Treasury Secretary. (3) **Strictness:** tune `link_confirm` so general nouns ("levy", "duty")
> don't link to narrow named schemes; record precision on the M2 spot-check set before/after.
> (4) **Russell mislink:** remove the Russell Indexes / FTSE Russell aliases from S&P Dow Jones
> Indices and add a merge-refusal rule and test for distinct named organisations. (5) **Held-out
> set to 30 articles** (15 today + 15 new, never in the corpus; the held-out guard enforces it),
> then measure linking on all 30 with `scripts/eval_heldout.py`.

**Acceptance**
- Frozen-graph link rate on the 30-article held-out set: business ≥ 75%, non-business aim 60%
  (under 50% stops the milestone for Sourabh), with precision on the
  spot-check set not lower than M2.1's (report both, before and after, in `evals/` and STATUS).
- Chancellor (UK) links to a UK concept, not the US Treasury Secretary; "levy" no longer links to
  a named scheme; Russell mentions no longer link to S&P Dow Jones Indices (tests).
- A new article with an unknown concept grows the graph by a verified concept (definition,
  prerequisites from existing concepts, acyclic), the article's demand links to it, and the new
  concept appears in the next library score; caps and budget respected (tests offline, one live
  run).
- `concepts.json` in GCS has a new version and a backup of the previous one; the API loads it.
- Open domains: the taxonomy is the only domain list in API and web; a new concept from a
  non-business article lands in the right domain; onboarding and calibration work for a reader
  who picks only non-business interests; the held-out report has a per-domain table.

**You or the agent:** 15 more held-out URLs (not in the corpus), including non-business articles.

---

## M7.5 — "For you" feed, "Read any link", reading goals (Oct 12–13)
**Scope (decided 2026-10-10, decision 33): everything below is required.** Signed-in (Google)
readers; demo personas are unchanged. DESIGN gets new sections for the feed and goals.

**Prompt**
> (1) **"For you" feed:** per interest topic, Tavily (articles, podcasts) and YouTube (video),
> ranked by interest, format affinity and readiness (concepts new to the reader, but not too
> many). Opening an item uses two-phase "Open here". Search queries are taxonomy topic names only,
> never reader text or history. Results are cached per (topic, format, day) and shared; add caps
> and budget lines. (2) **"Read any link"** box on the library, through the existing ingest path
> and per-user cap. (3) **Reading goals** in `users/{uid}/goals` (covered by export and delete):
> habit goals (articles or minutes per week, from reading events) and learning goals ("understand
> X", resolved through the graph linker to a target concept set; the feed boosts items covering
> them; progress = targets at band "known", shown on the profile page and the knowledge map).

**Acceptance**
- A Google reader with non-business interests gets a feed of articles, podcasts and videos for
  those topics; queries contain only taxonomy topic names (test); cache hits on the same
  (topic, format, day) make no search call; caps and budget lines hold.
- Opening a feed item shows the article within 5 s (two-phase).
- "Read any link" ingests a pasted URL within the per-user cap and refuses beyond it.
- A habit goal's progress matches the week's reading events; a learning goal resolves to concepts,
  boosts matching feed items, and its progress shows on the profile page and the knowledge map;
  goals appear in export and go on delete.

---

## M9 — Evaluation, hardening, demo, submission (Oct 15–17)

Oct 15 hardening and evals (after M2.2); Oct 16 demo seeding, README, video and deck;
Oct 17 submit.

**Required before the Oct 16 freeze (Sourabh, 2026-10-10, from the M2.2 live check):**
1. **Same-article duplicate concepts from growth** (live: "Forever chemicals" vs "PFAS"): run the
   merge check within one growth batch before defining, so one article never grows two concepts
   for the same idea.
2. **Wrong grown prerequisites** (live: PFOS → PHOSITA): validate prerequisites against the
   concept's domain, or drop low-confidence picks.
3. **Re-measure grown-concept precision on a fresh, independent sample of 30.** The 97% was a
   re-sample after tuning (the first sample was 87%); report both, plus the fresh one.
4. **README and deck state the frozen-graph misses** (business 64% vs the 75% target,
   non-business 13%) alongside the after-growth numbers (89% / 66%).

**Prompt**
> Build the quality evals per docs/DESIGN.md §12.1 and §12.4: load `evals/gold/*.json` (spans a
> human marked per persona), compute annotation precision/recall per persona at balanced density,
> cost per article and per explanation, cache hit rate and p95 latency; write `evals/report.md`.
> Set Cloud Run max instances 3 and finish rate limits. Switch CI deploy to Workload Identity
> Federation. Create a Cloud Monitoring dashboard (requests, errors, p95, daily LLM spend).
> Re-seed the persona templates (`scripts/seed_personas.py`, built in M4) against the final
> graph, pre-ingest the demo articles, and refresh README.md (merged in #12) with the eval
> results.

**You do by hand:** label the gold set (30 articles × 2 personas, split with your teammate,
start this on Oct 12); record the 3-minute video (same article, two personas side by side; the
verifier catching a bad explanation; the graph page showing learning); build the PDF deck with
the eval numbers; set Cloud Run min instances to 1 for Oct 19 – Nov 6; submit on Oct 17.
Load the unpacked extension for the video (Developer mode).
