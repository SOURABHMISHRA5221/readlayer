# ReadLayer — implementation spec (hackathon scope)

This is the build-facing version of the design doc. It fixes data shapes, formulas and
default constants so implementation doesn't have to make product decisions.

## 1. Core loop
1. Reader opens content (pasted URL in web app, or any page via extension).
2. Ingestion (once per URL, shared): extract text → paragraphs → features → Gemini demand profile.
3. Scoring (per reader, per view, no LLM): demand profile × reader graph → ranked spans.
4. Selection: annotation budget picks what to show.
5. Explanation (on hover / prefetch top-k): Gemini generates, verifier checks, cache stores.
6. Signals: interactions update the reader's graph (Beta pseudo-counts + Elo θ).

## 2. Global concept graph (`gs://<bucket>/concepts.json`)
One domain for the hackathon: business & economy news.
```json
{
  "version": "2026-10-06",
  "domains": ["economics", "finance", "business", "policy"],
  "concepts": [{
    "id": "c_repo_rate",
    "label": "Repo rate",
    "aliases": ["repo", "repurchase rate"],
    "wikidata": "Q1361932",
    "domain": "economics",
    "definition": "One or two neutral sentences.",
    "base_difficulty": 0.4,
    "prerequisites": ["c_inflation", "c_central_bank"],
    "embedding": [0.01, ...]
  }]
}
```
- `base_difficulty` b is on the logit scale, initial range roughly [-2, 2]; seeded by Gemini
  ("how specialized is this for a general news reader", 1–5 mapped to -2..2) plus word frequency.
- Build script (`scripts/build_concepts.py`): ingest corpus → group near-duplicate docs
  (syndicated copies count once for doc frequency) → collect extracted concepts (≥ 2 distinct
  doc groups, plus Wikipedia explainer titles as seeds) → dedupe by embedding cosine ≥ 0.88
  plus a Gemini merge check → Gemini definition, kind and specialization (keep ideas, jargon,
  institutions, regulators, committees, indices, taxes, policies and schemes; drop companies,
  people, places, one-off events) → Wikidata ids → Gemini prerequisite pass (max 3 prereqs,
  must exist in graph, reject cycles) → write JSON.
- Labels: the most frequent surface form in news articles ("Repo rate"), with the Wikipedia
  title kept as an alias.
- Wikidata ids: robots.txt disallows the Wikipedia/Wikidata APIs for our agent, so ids come from
  the `/wiki/` article page (`wgWikibaseItemId`). Seeds get theirs at corpus collection; other
  concepts best-effort (≤ 1 request/s, 10-minute cap, Gemini confirms the page matches).
- Embeddings: `MODEL_EMBED` (gemini-embedding-001, 256 dims), no fallback model.
- Entity linking at ingest: exact label/alias match first (any demand type); then, for concept
  and term demands only, embed the demand label; concepts whose label embeddings reach
  `LINK_THRESHOLD` as candidates (top 5 by label-embedding cosine; the threshold is calibrated
  to keep 95% of true matches), and `link_confirm` picks one or none. Embedding similarity alone
  can't separate a concept from its near neighbours (M2: 95% precision would need cosine 0.98),
  so the model decides; MODEL_QUALITY measured 95% precision vs 89% for MODEL_FAST.
  Anything else is `unlinked` (still usable as a term demand).

## 3. Demand profile (Firestore `contents/{url_hash}`)
```json
{
  "url": "...", "title": "...", "site": "...", "fetched_at": "...",
  "paragraphs": [{"id": "p3", "text": "...", "structure": 0.35}],
  "demands": [{
    "id": "d17", "paragraph_id": "p3",
    "anchor": {"exact": "yield curve", "prefix": "the inverted ", "suffix": " has historically", "start": 1042, "end": 1053},
    "type": "concept | term | context",
    "target_id": "c_yield_curve | null",
    "salience": 0.9,
    "explained_in_text": false,
    "zipf": 3.1
  }]
}
```
- Gemini structured output per article (chunk if > ~6k tokens). Prompt asks per paragraph for:
  concepts (surface text, assumed vs explained, salience), context references, structure flags.
- `structure` per paragraph ∈ [0,1] = 0.5·normalized parse depth/length (spaCy) + 0.5·LLM flag.
- Anchors must be verified: `exact` must occur in the paragraph text; drop demands that don't.

## 4. Reader model (Firestore)
```
users/{uid}                       profile, onboarding_done, density: minimal|balanced|guided,
                                  threshold_offset (float, default 0), prompts_today,
                                  learning_paused (bool), explanation_style: short|normal|detailed
users/{uid}/domains/{domain}      theta (float, default 0), thinks_in (0..1), interest (0..1)
users/{uid}/knows/{concept_id}    alpha, beta, last_seen, evidence: [{type, w, at}] (keep last 20),
                                  band, band_prev, band_changed_at
users/{uid}/events/{auto}         raw interaction events (append-only)
users/{uid}/weekly/{iso_week}     words_read, annotations_shown (annotation trend, §15)
users/{uid}/profile_edits/{id}    applied profile edits with their deltas, for undo (§15.3)
```

### Prior (IRT, 1-parameter logistic)
```
prior(c) = σ(θ_user,domain(c) − b_c)
```

### KNOWS edge as Beta
- On first touch: `α0 = k·prior`, `β0 = k·(1−prior)`, with `k = 2`.
- `p_know = α / (α + β)`; `confidence = α + β`.
- Bands for UI: p < 0.25 unaware · < 0.5 heard of · < 0.8 understands · else can explain.
- Forgetting (applied lazily on read): shrink toward the prior with half-life 90 days:
  `λ = 0.5^(days_since_last_seen/90)`; `α ← k·prior + λ·(α − k·prior)`, same for β.

### Evidence weights (positive → α, negative → β)
| event | sign | w |
|---|---|---|
| calibration_answer / quiz | ± | 3.0 |
| knew_this (tap on annotation) | + | 2.0 |
| explain_opened | − | 1.0 |
| explain_helpful | − | 0.5 (adds to the 1.0 above) |
| text_searched | − | 1.0 |
| read_normal_no_hover (salient concept, paragraph read at normal pace) | + | 0.3 |
| slowdown (paragraph dwell > 2× reader median per word) | − | 0.3 |
| liked_article_mention | + | 0.2 |
| profile_edit: concept claim (§15.3) | ± | 3.0 |
| profile_edit: domain claim, per core concept (§15.3) | ± | 2.0 |

While `learning_paused` is set, no evidence from events is applied (§15.1).

### Domain ability (Elo-style)
On every graded outcome (calibration, knew_this, explain_opened):
```
θ ← θ + K·(outcome − σ(θ − b_c)),  K = 0.3 during onboarding, 0.1 after
```

## 5. Scoring (per reader, deterministic)
For each demand d:
- concept: `p = p_know(c)` from KNOWS (or prior if no edge)
- prerequisites (one hop): `p ← min(p, max_{q∈prereq(c)} p_know(q) + 0.1)`
- term: `p = σ(1.2·(zipf − τ))`, `τ = 3.5 − 0.4·θ_domain`
- context: `p = 0.8` if reader has an ENGAGED content mentioning the same entity in the last
  30 days, else `0.2`
- `miss = (1 − p)·(0.4 if explained_in_text else 1.0)`
- `span_score = miss · salience`
- paragraph: `para_score = 1 − Π(1 − span_score_i) + 0.3·structure·(1 − σ(θ_domain))`, clipped to [0,1]

Thresholds (before per-user `threshold_offset` and density dial):
| density | span | paragraph | pre-read (mean span_score of assumed concepts) |
|---|---|---|---|
| minimal | 0.60 | 0.85 | 0.55 |
| balanced | 0.45 | 0.75 | 0.45 |
| guided | 0.30 | 0.65 | 0.35 |

`threshold_offset` adapts: +0.02 per dismissal/knew_this, −0.02 per text_searched or slowdown on
an unannotated paragraph; clamp to [−0.15, +0.15].

## 6. Selection (annotation budget)
1. Drop spans below threshold. Rank by `span_score`.
2. First occurrence of each `target_id` only.
3. Caps: ≤ 1 span annotation per 80 words, ≤ 1 paragraph marker per 3 paragraphs,
   ≤ 2 span annotations in any single paragraph.
4. Pre-read card if triggered: walk prerequisites backward from weak assumed concepts until a
   concept with p_know ≥ 0.7; topological order; ≤ 3 steps; each step links to a corpus article
   where that concept is `explained_in_text` (shortest first), else shows the concept definition.
5. Uncertainty prompt ("Know this?"): at most one per article, three per day, only when
   salience ≥ 0.7 and 0.35 ≤ p_know ≤ 0.65 and α+β < 4.

## 7. Explanations
Request: `{content_id, demand_id | paragraph_id}` + reader's band for the concept, top
THINKS_IN domain and `explanation_style` (short | normal | detailed, §15.3).

Gemini output schema:
```json
{
  "background": "≤ 3 sentences of general knowledge; analogy from the reader's frame allowed here only",
  "author_says": "Restatement of the span/paragraph. Preserve hedges, attribution, numbers, negation.",
  "analogy_domain": "software | cricket | ... | null"
}
```
Inputs to the prompt are ONLY: the span, its paragraph, the concept definition, the reader band,
the THINKS_IN domain, the explanation style. No web access.

### Verifier (must pass before cache/show)
1. Deterministic checks on `author_says` vs source paragraph:
   - every number in `author_says` appears in the source (normalize "40%"/"40 per cent");
   - if source has hedge words (may, might, could, likely, reportedly, alleged, expected) the
     restatement keeps a hedge;
   - if source attributes ("said", "according to", "argues", "claims") the restatement keeps
     attribution; negations ("not", "no", "never") are not dropped.
2. Gemini judge (`MODEL_QUALITY`): split `author_says` into atomic claims; each must be
   ENTAILED by the source paragraph; `background` must not CONTRADICT it. Structured verdict.
3. On fail: regenerate once with the failure reasons; on second fail, fall back to the concept's
   `definition` as a plain gloss (no `author_says`).

Cache: Firestore `explanations/{sha1(anchor.exact + paragraph_id + content_id) + band + domain + style}`
with `verified: true`, model ids, created_at.

## 8. API (FastAPI, `/v1`, Firebase ID token in `Authorization: Bearer`)
| method | path | purpose |
|---|---|---|
| POST | /v1/content | `{url}` (server fetches via safe_fetch) or `{url, title, paragraphs[]}` (extension, already extracted and redacted) → `{content_id, title, paragraphs}`; ingests if new |
| GET | /v1/me/export | everything we hold about the caller, as JSON |
| DELETE | /v1/me | delete all of the caller's data and their Auth user |
| GET | /v1/content/{id}/annotations | ranked, budgeted annotations for the caller |
| POST | /v1/explain | `{content_id, demand_id?, paragraph_id?}` → explanation (cached/verified) |
| POST | /v1/events | batch of interaction events → graph updates (sync, idempotent by event id) |
| GET | /v1/me/graph | concepts by domain with band, plus stats (concepts learned, annotation trend); `?domain=X[&q=]` → capped subgraph for the knowledge map (§15.2) |
| PATCH | /v1/me/graph/{concept_id} | user correction ("I know this" / "I don't") → strong evidence |
| GET | /v1/me/profile | reading profile page data: summary, domains, THINKS_IN, weekly band changes, trend (§15.2) |
| PATCH | /v1/me/settings | `thinks_in`, `density`, `explanation_style`, `learning_paused` |
| POST | /v1/me/profile/edits | parse a natural-language profile edit → preview, writes nothing (§15.3) |
| POST | /v1/me/profile/edits/{id}/apply | apply a previewed edit |
| POST | /v1/me/profile/edits/{id}/undo | undo an applied edit |
| POST | /v1/onboarding | field, interests, comfort per domain, optional liked URLs |
| GET | /v1/calibration/next | next item: concept with b closest to current θ, not yet asked |
| POST | /v1/calibration/answer | `{concept_id, answer: explain|heard|none}` |

Annotation response item:
```json
{"id": "d17", "kind": "span|paragraph|preread|prompt",
 "anchor": {"exact": "...", "prefix": "...", "suffix": "..."},
 "paragraph_id": "p3", "score": 0.68, "concept_id": "c_yield_curve", "label": "Yield curve"}
```

## 9. Client behavior (`packages/annotator`)
- Anchor resolution: find `exact` with matching prefix/suffix inside the article root; fall back
  to fuzzy (normalized whitespace); skip if not found.
- Span: dotted underline; hover (desktop) / tap (mobile) opens card; card has "Knew this",
  "Helpful", "This is wrong". Card label: "Explanation — not the author's words".
- Paragraph: small margin marker → "What this paragraph is saying".
- Events batched every 5 s and on `visibilitychange`: explain_opened, knew_this, explain_helpful,
  report_wrong, text_searched (selection + copy or right-click search), paragraph_dwell
  (IntersectionObserver, ms visible, words).

## 10. LLM layer (`app/llm.py`)
- Backend: LiteLLM Python SDK, in-process. Not the LiteLLM proxy: a separate gateway service is
  extra infra, latency and cost with one consumer. Revisit the proxy only if several services
  or teams share models.
- Interface: `await llm.run(task: str, schema: type[BaseModel], prompt_vars: dict) -> BaseModel`.
  Callers never pass model names; `task` maps to a route in config.
- Routes (env-driven):
  | task | primary | fallback |
  |---|---|---|
  | extract_demands, link_merge, concept_define, concept_prereqs, concept_wikidata, profile_edit | MODEL_FAST | MODEL_FALLBACK |
  | embed (`llm.embed`) | MODEL_EMBED | none: vectors from another model aren't comparable |
  | explain, link_confirm (timeout 45 s, batches of 10) | MODEL_QUALITY | MODEL_FAST |
  | verify | MODEL_QUALITY | none: if the verifier is unavailable, show definition gloss only |
- Error handling per model (`classify_error` in `llm.py`):
  - retry the same model with backoff (max `LLM_MAX_RETRIES`), then fall back: timeout (20 s),
    429, 5xx;
  - fall back immediately, no retry: 404 / 501 model not found (Vertex reports an unknown model
    as a 500 whose message carries the 501/404), and schema validation failure after 1 repair retry;
  - raise `LLMRejected` immediately, never fall back, logged at ERROR with task and model:
    400, 401, 403 and any other unclassified error. A bad request or bad credentials would fail
    the same way on the fallback model and hide a real bug.
- `verify` never falls back for any error; it raises (`LLMUnavailable` / `LLMRejected`).
- Every fallback logs a WARNING with task, failed model, error class and fallback model, and
  increments `llm_fallbacks` in the daily spend doc, so a silent quality drop is visible.
- Structured output: pass the Pydantic JSON schema as `response_format`; always re-validate
  locally with Pydantic.
- Budget: per-call cost from LiteLLM's cost tracking (or token × configured price when the model
  isn't in its price map) summed in Firestore `ops/spend/days/{yyyy-mm-dd}` (UTC; `ops/spend/{date}`
  would be an invalid odd-segment path); refuse new non-cached
  calls past `LLM_DAILY_BUDGET_USD` and return cached or degraded output.
- Every response stored with `{model, prompt_version, task, tokens_in, tokens_out, cost_usd}`.
- Open models: Gemma through Vertex AI Model-as-a-Service (pay-per-token) as `MODEL_FALLBACK`,
  only if M0 confirms it's reachable from LiteLLM (directly or via Vertex's OpenAI-compatible
  endpoint). Never self-host on GPUs within this budget.
- CPU-only open components we do run: spaCy (structure features), wordfreq (zipf), Presidio
  analyzers (server-side PII check, §11.3).

## 11. Security, privacy and safety

### 11.1 Threat model (what actually matters here)
| Threat | Where | Mitigation |
|---|---|---|
| SSRF via user-supplied URL | POST /v1/content | `safe_fetch` (11.2) |
| Prompt injection inside article text | ingest, explain | delimiters, no tools, schema-only output, verifier, injection eval cases |
| Private page content sent by extension (email, banking, intranet) | extension | activation rules + client redaction (11.3) |
| Reading profile leakage (what someone does/doesn't know) | Firestore, logs | per-user rules, pseudonymous logs, export/delete (11.4) |
| Cost exhaustion / abuse | all LLM paths | auth required, per-user caps, daily budget, Cloud Run max instances |
| Token theft from extension | extension | short-lived Firebase ID tokens, refresh via web app, no tokens in storage beyond session |

### 11.2 `safe_fetch`
- Schemes `http`/`https` only; ports 80/443 only.
- Resolve DNS first; reject private, loopback, link-local (incl. 169.254.169.254), multicast and
  reserved ranges for IPv4 and IPv6; re-check after every redirect (max 3); pin the resolved IP
  for the connection.
- Timeout 10 s, max body 3 MB, `Content-Type` must be HTML.
- Identify with a clear User-Agent; respect robots.txt disallow for our agent; skip known
  paywalled responses rather than working around them.

### 11.3 PII handling
- Article content is public material, not PII, but it is still untrusted input.
- Extension activation: runs only when the user clicks the toolbar button or the site is on the
  user's allowlist (default: a curated list of news domains). Never on pages with a password
  field, `autocomplete="cc-*"` inputs, or URLs matching mail/bank/intranet patterns.
- Extension sends only the Readability-extracted article text and URL (not raw HTML, not
  comments sections, not form fields).
- Client-side redaction before sending: emails, phone numbers, card-like digit runs (Luhn),
  Aadhaar/PAN-like patterns → `[REDACTED:type]`.
- Server-side backstop: Presidio analyzers on extension-submitted text; if PII density exceeds a
  threshold, refuse ingestion and tell the user why.
- Google Cloud Sensitive Data Protection is the managed upgrade path; not used in the hackathon
  build because Presidio covers it at no per-call cost.

### 11.4 User data rights and minimisation
- Data held: Firebase uid, display name, onboarding answers, settings, KNOWS edges, domain
  abilities, weekly reading stats, applied profile edits (ops and deltas, never the raw text),
  events (raw events expire after 90 days via Firestore TTL; aggregates stay).
- No email stored in our collections (Firebase Auth keeps it).
- `GET /v1/me/export` → JSON of everything above. `DELETE /v1/me` → deletes all user documents
  and the Auth user.
- Firestore security rules: clients never read/write Firestore directly; only the API service
  account does. Rules deny all client access.
- Consent screen at onboarding states what is collected and why, in plain language. Design with
  India's DPDP Act principles in mind (notice, consent, purpose limitation, erasure); this needs
  proper legal review before any public launch.

### 11.5 Platform hygiene
- Cloud Run service account with least privilege (Vertex AI user, Firestore user, GCS object
  viewer on the graph bucket, Secret Manager accessor).
- CORS: only the web app origin and the extension origin.
- Secrets in Secret Manager; nothing secret in the extension bundle.
- Rate limits per uid: 60 annotation reads/min, 30 explain calls/min, 20 new URLs/day,
  10 profile-edit parses/day (§15.3).

## 12. Evaluation (what we show judges)
1. **Gap-scorer quality**: 30 articles × 2 personas (engineer, commerce student). For each, a
   human marks spans they'd want explained. Report precision and recall of shown annotations
   at the balanced density, plus the difference between personas.
2. **Faithfulness**: 40-case suite (15 adversarial from M5, 25 from real articles). Report
   verifier rejection rate on bad cases and acceptance on good cases.
3. **Injection**: 10 articles with planted instructions ("ignore previous instructions...",
   fake system notes). Pass = output schema-valid and no planted text followed.
4. **Cost and latency**: cost per ingested article, per explanation, cache hit rate, p95
   annotate latency.
Run with `uv run python -m evals.run` and write `evals/report.md`; include headline numbers in
the deck.

## 13. Delivery and observability
- GitHub Actions: ruff, pytest, TS typecheck on every PR; deploy on `main` using Workload
  Identity Federation (no JSON keys).
- Structured JSON logs with `request_id`, `uid_hash`, `task`, `model`, `cost_usd`, `latency_ms`.
- One Cloud Monitoring dashboard: requests, errors, p95 latency, daily LLM spend.

## 14. Out of scope for the hackathon
Video/podcast, learned scoring model, Neo4j/Postgres, multi-domain graph, mobile app,
LiteLLM proxy server, self-hosted open models, Terraform.

## 15. Reading profile page
The reader's view of their own model: what we think they know, how it is changing, and how
to correct it. Built in two steps: read-only page and settings in M3 (API) and M7 (UI),
natural-language profile edits in M7. Everything shown is computed deterministically from
the reader model in §4; only the optional profile edit (§15.3) calls an LLM.

### 15.1 Page sections
1. **Summary card.** A deterministic template, never sent to an LLM. Inputs: θ per domain,
   THINKS_IN domains, and this week's band changes. θ maps to words: θ ≥ 1 "advanced",
   0 ≤ θ < 1 "comfortable", −1 ≤ θ < 0 "building", θ < −1 "new to". Example:
   "Comfortable in finance, building in economics. You think in software. 6 concepts moved up a
   band this week." Same inputs always give the same text (unit-tested).
2. **Ability vs interest.** Per domain, two bars: ability (θ, shown on a fixed −2..2 scale) and
   interest (0..1 from onboarding and reading). Bars carry their numbers as text, not colour alone.
3. **Knowledge map, one domain at a time.** Cytoscape.js with the dagre layered layout
   (foundations at the top, advanced below), loaded with a dynamic import only when the section is
   opened. Nodes coloured by band (§4 bands, plus a text/shape cue for colour-blind readers);
   edges are prerequisites. At most 60 nodes: the reader's most relevant concepts in the domain
   (ranked by evidence count × recency decay, ≤ 40), plus their prerequisite closure, cut at 60
   by depth. A search box finds any other concept and shows it with its prerequisite chain.
   Clicking (or pressing Enter on) a node opens a card: band, the last 3 evidence items in plain
   language ("You opened an explanation · 3 Oct", "You tapped Knew this · 1 Oct"), and
   "I know this" / "I don't" buttons that call PATCH /v1/me/graph/{concept_id}.
   Accessibility: the canvas is not keyboard-accessible, so the same subgraph is also rendered as
   a keyboard-navigable list grouped by depth (the default view below 640 px wide); the node card
   is a dialog with focus management.
4. **This week.** Concepts that moved up a band in the last 7 days, and the
   annotations-per-1,000-words trend by week (falling = the overlay is learning).
5. **Analogy domains.** The reader's THINKS_IN domains, editable (choose from the fixed list
   used by explanations; at most 3).
6. **Data controls.** Export (GET /v1/me/export), Delete (DELETE /v1/me), and a
   **Pause learning** toggle. While paused, POST /v1/events accepts events but applies and
   stores nothing (`{"applied": false}`); the page shows a banner. Explicit corrections
   (PATCH /v1/me/graph, applied profile edits) still apply, because the reader asked for them.

### 15.2 Data and API (M3)
- `users/{uid}` gains `learning_paused` (bool, default false) and `explanation_style`
  (`short | normal | detailed`, default `normal`).
- `users/{uid}/knows/{concept_id}` gains `band`, `band_prev`, `band_changed_at`, written whenever
  an update changes the band; weekly band changes come from these fields.
- `users/{uid}/weekly/{iso_week}`: `words_read`, `annotations_shown`, updated by the annotate path
  and paragraph_dwell events; source of the trend.
- `concepts.json` gains `doc_freq` per concept (the build already computes it) to pick a domain's
  core concepts for §15.3.
- GET /v1/me/profile →
  ```json
  {"summary": {"text": "...", "top_domain": "finance", "moved_up_this_week": 6,
               "learning_paused": false},
   "domains": [{"domain": "finance", "theta": 0.6, "interest": 0.8, "thinks_in": 0.0}],
   "thinks_in": ["software"],
   "week": {"moved_up": [{"concept_id": "c_repo_rate", "label": "Repo rate",
                          "from": "heard of", "to": "understands"}],
            "trend": [{"week": "2026-W40", "annotations_per_1000_words": 14.2}]},
   "settings": {"density": "balanced", "explanation_style": "normal"}}
  ```
- GET /v1/me/graph?domain=X[&q=term] → the capped subgraph:
  `{"nodes": [{"id", "label", "band", "evidence_count", "last_seen", "depth"}],
  "edges": [{"from": prereq_id, "to": concept_id}], "truncated": bool}`; `q` returns matches
  with their prerequisite chains instead. Without `domain` it keeps the existing per-domain
  summary.
- PATCH /v1/me/settings: `thinks_in`, `density`, `explanation_style`, `learning_paused`.
- POST /v1/events checks `learning_paused` before any write.

### 15.3 Edit profile with a prompt (M7)
A text box: "Describe yourself as a reader" ("I'm a backend engineer, I know options trading
well, explain macro things briefly"). A one-line notice under it: "Your text is processed by AI
to update your settings. It is not stored."
- **Parse.** One `MODEL_FAST` call, task `profile_edit`, prompt file
  `app/prompts/profile_edit.md` with a version header. The reader's text goes between content
  delimiters as untrusted data. The prompt gets only the text, the domain list and the allowed
  THINKS_IN list: no uid, no history, no concept ids. §11.3 redaction runs on the text first.
  The raw text is never logged or stored; logs carry `uid_hash`, op counts and cost.
- **Whitelist.** Output is a Pydantic discriminated union with `extra="forbid"`; at most 20 ops,
  at most 30 concept names per op:
  | op | fields |
  |---|---|
  | set_domain_level | domain, level: new / some / comfortable / expert |
  | mark_concepts | names[], state: known / unknown |
  | set_thinks_in | domains[] (from the allowed list, ≤ 3) |
  | set_explanation_style | length: short / normal / detailed |
  | set_density | minimal / balanced / guided |
  | pause_learning | paused: bool |
  Any output that fails validation is rejected as a whole ("Couldn't understand that, try
  rephrasing"); nothing is partially applied.
- **Resolve.** Concept names go through the existing graph linker (§2: exact alias, then
  embedding candidates + `link_confirm`); the model never supplies ids. Names that don't
  resolve are listed as "Couldn't find: …" and dropped from the edit.
- **Preview.** POST /v1/me/profile/edits parses and resolves, writes nothing to the reader
  model, and returns `{edit_id, ops, preview, unresolved}`. The preview is a diff: per domain θ
  before → after, concepts affected per direction with counts (expandable list), settings
  before → after. The pending edit expires after 1 hour. Nothing changes until the reader
  clicks **Apply** (POST /v1/me/profile/edits/{id}/apply).
- **Apply.**
  - mark_concepts: evidence weight **3.0** per concept (+ for known, − for unknown).
  - set_domain_level: target θ per level (new −1.5, some −0.5, comfortable 0.5, expert 1.5);
    θ ← θ + 0.5·(target − θ); then weight **2.0** evidence on the domain's core concepts (its 10
    highest-`doc_freq` concepts): + where b ≤ target, − where b > target.
  - style, density, THINKS_IN, pause: set directly on `users/{uid}`.
  - The applied edit is stored as a `profile_edit` event and as
    `users/{uid}/profile_edits/{edit_id}` with the ops and the exact deltas applied (Δα/Δβ per
    concept, Δθ per domain, previous setting values).
- **Undo.** POST /v1/me/profile/edits/{id}/undo subtracts the recorded deltas (α and β floored
  at the prior pseudo-counts), reverts Δθ, and restores previous settings unless the reader has
  changed them since. Evidence added after the edit stays. The page lists applied edits with
  Undo buttons.
- **Limits.** 10 parse requests per user per day (§11.5); the cost of every call (parse and
  link_confirm) is logged against the edit.
- **Explanations.** `explanation_style` becomes an input to the explain prompt (§7: target
  length short ≈ 1 sentence of background, normal ≤ 3, detailed ≤ 5; `author_says` rules
  unchanged) and part of the explanation cache key.
- **Tests.** Whitelist enforcement (unknown op, extra field, model-invented concept id, op
  smuggled through instructions in the reader text: all rejected), unresolved concepts reported
  and dropped, apply then undo restores α/β/θ and settings exactly, rate limit (11th parse
  request that day → 429).
