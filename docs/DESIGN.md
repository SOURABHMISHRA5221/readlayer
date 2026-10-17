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
Open domains (decision 33): one fixed taxonomy of 14 top-level domains. The graph started from a
business & economy corpus; online concept growth (M2.2) adds concepts in any domain. Demo
personas stay curated on the original four.
```json
{
  "version": "2026-10-06",
  "domains": ["economics", "finance", "business", "policy", "politics", "law", "technology",
              "science", "health", "environment", "sports", "culture", "education", "society"],
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
- `base_difficulty` b is on the logit scale, range [-2, 2]: 0.75 × (specialization 1–5 mapped
  to -2..2) + 0.25 × word-frequency term (4 − zipf, clamped), so rarer words are harder.
- Build script (`scripts/build_concepts.py`), in order:
  1. **Near-duplicate docs.** Syndicated or near-identical articles form one group: 5-word-shingle
     Jaccard ≥ 0.5, or title+lead embedding cosine ≥ 0.92 confirmed by Jaccard ≥ 0.15. Doc
     frequency (`doc_freq`) counts distinct groups, so a syndicated story counts once.
  2. **Candidates.** Every demand label from the corpus, normalised (casefold, punctuation and
     parentheticals removed, trailing plural folded), plus Wikipedia explainer titles as seeds.
     Single-article labels are candidates too; the keep rule in step 4 filters them.
  3. **Dedupe.** Label embeddings; pairs with cosine ≥ `DEDUPE_THRESHOLD` (0.88, top 5 per label)
     go to a `link_merge` check; accepted pairs are merged transitively, then the overrides
     file (below) is applied.
  4. **Define and keep.** `concept_define` returns definition, domain, specialization and kind.
     Kept kinds: idea, jargon, instrument (bond, ETF, derivative), entity_type (a *type* of firm
     or fund: hedge fund, brokerage firm, subsidiary, NBFC), market_event (a recurring
     phenomenon: bank run, bond sell-off), unit (crore, lakh), institution, regulator,
     committee, index, tax, policy, scheme. Dropped kinds: company (a specific named firm),
     person, place, event (a specific dated occurrence), generic. **Single-article rule:** a
     concept seen in fewer than 2 doc groups is kept only if its specialization is ≥ 2.
     Wikipedia seeds and override splits are always kept.
  5. **Wikidata ids** (best effort, below).
  6. **Prerequisites.** Per concept, `concept_prereqs` chooses from a pool of its 20 nearest
     concepts (label + definition embeddings) plus the 20 most frequent basic concepts
     (b ≤ 0). At most 3 prerequisites, existing ids only; cycles are broken by dropping the least
     confident edge (on a tie, the one whose prerequisite is harder than its dependent), and the
     result is asserted to be a DAG.
  7. Write `concepts.json`, calibrate `LINK_THRESHOLD` and re-link every content doc (below).
  LLM and embedding results are cached under `data/build_cache/`, so reruns only pay for what
  changed. `--project` estimates a full run's cost without LLM calls (exit code 2 above $8);
  a full run starts only if that projection is ≤ $8. The previous graph is kept as `concepts.prev.json` locally and in GCS.
- **Canonical labels.** The most frequent surface form in news articles ("Repo rate", "GDP"),
  counting only complete names and acronyms, never fragments; else the model's label; the
  Wikipedia title only when no article used the concept. The Wikipedia title is always kept as
  an alias.
- **Overrides** (`data/graph_overrides.yaml`, committed, applied on every build):
  `never_merge` label pairs are never joined by dedupe; `split` entries are pulled out of
  whatever concept they merged into (even transitively) and become their own, always-kept
  concept; `rename` replaces a label (the id follows it, the old label is hidden from aliases).
  `scripts.apply_overrides` patches an already-built graph the same way and re-links only the
  affected docs, without a rebuild. M2.2 adds `remove_alias` (aliases that made wrong exact-match
  links, e.g. "Tax" on Tax levy, "Russell Indexes" on S&P Dow Jones Indices), `add` (hand-written
  concepts with a required kept kind, e.g. Chancellor of the Exchequer, FTSE Russell) and
  `never_merge_kind` (an institution, regulator, committee, index or index provider never
  absorbs a differently-labelled concept).
- **Kind and jurisdiction (M2.2).** Every concept stores its `kind` (the concept_define kinds,
  plus `role`, `index_provider`, `condition`, `method`, `organism_type`) and a `jurisdiction`
  (ISO country code, `EU` or `global`). Pre-M2.2 concepts got both from `concept_jurisdiction`.
- **Glossary seeding (M2.2, decision 34).** Domains the business corpus never covered are seeded
  from Wikipedia glossaries (`data/glossaries.yaml`), fetched through `safe_fetch` and parsed
  deterministically (`app/graph/glossary.py`: glossary and plain definition lists, bold-term
  lists, heading-per-term pages). Exact matches of existing concepts are dropped; each glossary
  group keeps its 300 most common terms; dedupe (nearest graph concept and the 3 nearest
  candidates, ≥ DEDUPE_THRESHOLD, then `link_merge`); `concept_define` v3 writes our own
  definition (Wikipedia's text is a context snippet only, never stored); kept kinds only; **never
  a single everyday word** (one word with Zipf ≥ 4.5: "Health", "Level" would carry a glossary
  sense onto every ordinary use under exact-match linking); prerequisites from the 20 nearest and
  20 most basic same-domain concepts. `scripts.seed_glossaries --dry-run` writes only a local
  file and `apps/api/evals/seed_report.md`; the upload waits for Sourabh's yes.
- **Online growth (M2.2, decision 35).** After linking, a new article's unlinked concept/term
  demands may grow verified concepts (taxonomy domain, kept kind, specialization ≥ 2, not an
  everyday word, prerequisites existing ids only, acyclic): one batched `link_merge` against near
  graph concepts, one batched `concept_define`, one batched `link_confirm` (MODEL_QUALITY: would
  the new definition explain the mention in its sentence? drops wrong senses and generic words;
  ≈ $0.004 and up to ~30 s more per growing article), one batched `concept_prereqs`. Slots are
  reserved **when growth runs, in phase 2, for exactly the labels it will try** (M9 part 1,
  decision 56; one define call per label, merged or rejected labels cost too), from the reader
  whose request runs phase 2, through a closure: no uid on shared content, nothing reserved before
  a fetch succeeds, nothing to refund. ≤ 5 per article, 25 per reader and 100 per day for the
  service by default; production runs 60 per reader and 300 per day since decision 53
  (2026-10-13, `deploy.env.yaml`), and all anonymous readers share 150 a day
  (`ANON_GROWTH_DAILY_CAP`). Scripts and the corpus pass no reserver and never grow. When the caps
  cut growth short the page is stored with `grow_pending: true`; a reader's reopen then calls
  `POST /v1/content/{id}/grow` (§8), which grows only labels not tried before (`grow_tried`) under
  a claim on the page (one grower across instances). Only a reader's own pages (`NOT_CORPUS`)
  ever regrow; pages stored before M9 count only if they are extension pages never grown and not
  recordings, so library articles and seeded demo recordings never change under a judge.
  **Same-page duplicates (M9 part 2, decision 57):** growth's one `link_merge` call also asks
  whether picks of the same batch name one concept (label cosine ≥ `BATCH_NEAR` = 0.85, each
  pick's 5 nearest); "same" answers group picks (union-find), a group with a member that is a
  graph concept links there, otherwise its most salient pick is defined, the rest link to it and
  their labels become its aliases ("Forever chemicals" / "PFAS"). Measured: 61 real same-page
  pairs, 0 false merges, 0 missed (`apps/api/evals/merge_replay.md`). **Prerequisites:** no
  confidence or same-domain rule (neither separated wrong cross-domain edges from right ones,
  `apps/api/evals/prereq_replay.md`); edges judged wrong are dropped where the API builds its
  graph (`app/graph/prereq_fixes.py`, no data rewrite). Growth has its own timeout
  inside phase 2 and never fails the ingest; held-out URLs never grow. Concepts are stored
  create-if-absent in Firestore `graph_growth/` (no user data), merged at startup and polled
  every 60 s by each instance (server timestamps, 120 s overlap window), and folded into
  `concepts.json` later by `scripts.fold_growth` (backup first). `GROWTH_ENABLED` in
  `deploy.env.yaml` is the switch. Persona templates never change through growth.
- Wikidata ids: robots.txt disallows the Wikipedia/Wikidata APIs for our agent, so ids come from
  the `/wiki/` article page (`wgWikibaseItemId`). Seeds get theirs at corpus collection; other
  concepts best-effort (≤ 1 request/s, 10-minute cap, Gemini confirms the page matches).
- Embeddings: `MODEL_EMBED` (gemini-embedding-001, 256 dims), no fallback model.
- **Entity linking** (at ingest and in the build's re-link): exact label/alias match first (any
  demand type), except a one-word key that reaches a sense-labelled concept ("Pip (finance)",
  "Duration (bond)": a trailing parenthesis with 3+ lower-case letters, not an acronym like
  "(OMO)") or a sense-parenthesised alias ("Short (finance)"), unless the demand itself names
  that sense: those go the model's way below (decision 66; "Pip" on a UK benefits article had
  been linked to the forex pip unchecked). Otherwise, for concept and term demands only, embed the demand label; concepts
  whose label embedding reaches `LINK_THRESHOLD` become candidates (top 5), and `link_confirm`
  (MODEL_QUALITY) picks one or none. The threshold is recalibrated on every build to keep 95% of
  true matches, measured on exact-alias matches whose wording differs from the concept label,
  and written to `.env.example` (0.865 after M2.1). Embedding similarity alone can't separate
  a concept from its near neighbours (95% precision would need cosine 0.98), so the model
  decides; MODEL_QUALITY measured 95% precision vs 89% for MODEL_FAST.
  Anything else is `unlinked` (still usable as a term demand).
  **Jurisdiction (M2.2):** before the model sees them, candidates of a jurisdictional kind
  (role, institution, regulator, committee, policy, tax, scheme) from a country the paragraph
  gives no sign of (site, web address, currency symbols, country names and demonyms;
  `app/graph/jurisdiction.py`) are dropped; `link_confirm` v3 sees each candidate's kind and
  jurisdiction and the article's country signs, and refuses to link a specific named levy or
  scheme to its generic category. M2.2 keeps `LINK_THRESHOLD` at 0.865 for every run.
- **Held-out evaluation.** Coverage on the corpus the graph was built from is inflated
  (single-article concepts are made from those very mentions), so linker quality is measured on
  `data/heldout_urls.txt`: 15 fresh articles from the same feeds, ingested through the production
  path and reported by `scripts.eval_heldout`. **Rule:** held-out articles are never added to the
  corpus or used to build the graph; `build_concepts` refuses to run if the two lists overlap.
  The held-out number is the one to quote (M2.1: 57% exact-name, 5% model-confirmed, 38%
  unlinked). M2.2 grows the set to 30 (15 non-business, domain labels fixed before measuring,
  their demand set frozen with a sha256) and reports, per domain, the frozen-graph link rate (the
  headline), the after-growth rate (production behaviour) and grown-concept precision on a
  judged sample (`scripts.heldout_headline`, `apps/api/evals/heldout_report.md`).

## 3. Demand profile (Firestore `contents/{url_hash}`)
```json
{
  "url": "...", "title": "...", "site": "...", "fetched_at": "...",
  "source": "fetch | extension | user_ingested",
  "description": "publisher standfirst | null", "author": "Name; Name | null",
  "published": "2026-10-03 | null", "image": "https://… (og:image) | null",
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
- **Publisher metadata** (`description`, `author`, `published`, `image`) comes from the page's own
  metadata via trafilatura at ingest, shown as-is and never generated or rewritten. `image` must
  be an absolute http(s) URL; the UI hotlinks it with `referrerpolicy=no-referrer` and falls back
  to a typographic tile when it is missing or fails to load. `scripts.backfill_metadata` fills
  docs ingested before these fields existed (safe_fetch, no LLM).
- **`source`**: `fetch` (server fetched a submitted URL), `extension` (text extracted and redacted
  client-side), `user_ingested` (a reader opened a web recommendation with "Open here", §16).
  `user_ingested` docs are readable like any other but are never corpus or held-out data:
  `build_concepts` and `eval_heldout` skip them even if their URL is listed.
- **Two-phase ingest (M6).** Phase 1 (safe_fetch, extraction, paragraph ids; no LLM) stores
  `pending_contents/{url_hash}`: the article text and publisher metadata only, no user data,
  plus `attempts`, `lease_until` and a 24 h `expire_at` (Firestore TTL). Phase 2 (structure
  features, demand extraction, linking) takes a 150 s lease in a transaction, runs under a
  120 s timeout (so an expired lease always means the earlier run stopped), writes `contents/`
  with the **same paragraphs** and deletes the pending doc. Only analyses that ran and failed
  count as attempts (not budget refusals, a busy lease or a dropped request); after 3 the
  article is not retried (410). "Open here" runs phase 1 in its request and phase 2 in a second
  request from the reader page, so the article shows in seconds; POST /v1/content and the scripts
  run both back to back through the same pending doc and lease. A URL that is pending counts as
  known everywhere: no second fetch and no second ingest slot.
- **Warm on open and at startup (decision 69 C, C2).** LiteLLM and spaCy load lazily at import
  (importing the app stays light). Startup (`lifespan`, after the startup log, not awaited) and
  phase 1 (`fetch_and_extract`, `store_submitted`) start `app/warm.py` in a thread without
  waiting, so the imports overlap the fetch; `analyse_pending`
  awaits it in a thread inside its lease (the 30 s margin covers it). Run once per process, no model call. Measured before:
  the first analysis on an instance waited 11–17 s before its first model call, later ones
  < 0.5 s. `content ingested` logs `parse_ms`, `extract_ms`, `link_ms`, `grow_ms`; `llm embed`
  logs `latency_ms` and `attempts`.
- **Growth on a stored page (M9, §2).** `contents/` carries `grow_pending` (true when the caps cut
  growth short; absent on pages stored before M9), `grow_tried` (normalised labels already tried)
  and, while a reopen grows it, `grow_token` and `growing_until` (a random token, no reader data).
  A stored page's text never changes; its demand links can, by growth on reopen.
- **Media (§21).** A video or podcast's pending doc starts at `stage: "transcribe"` with a
  `media` block and no paragraphs; transcription fills the paragraphs (each with `start_s`) and
  moves it to `"analyse"`. `contents/` then carries `media` (`kind`, `video_id` or `audio_url`,
  `duration_s`, the transcript's model, prompt version, windows and cost) and `start_s` per
  paragraph. Old docs read as before.

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
users/{uid}/rec_signals/{persona_or_default}   Up next signals (§16): format stats, relation
                                  dismissals, seen items, recent event ids
users/{uid}/ingest_counts/{utc_day}            new URLs ingested that day (per-user cap)
users/{uid}/media_counts/{utc_day}             new videos and podcasts opened that day (§21)
users/{uid}/demo_graphs/{persona}             a demo reader's graph for one persona (below)
users/{uid}/goals/{goal_id}                   reading goals (§18): habit numbers or resolved
                                  learning targets (ids and labels, never the goal text)
users/{uid}/goal_resolve_counts/{utc_day}     learning-goal resolutions that day (cap, §18)
users/{uid}/ingested/{content_id}             pages this reader brought in (`at`, §17.4)
users/{uid}/growth_counts/{utc_day}           concepts grown from this reader's ingests (M2.2)
persona_feeds/{persona}                       demo For you snapshots (§17.3, not user data)
persona_templates/{persona}                   read-only seeded persona graphs (not user data)
```

**Demo personas (M4).** Anonymous demo readers pick a persona (newcomer, trader,
policy_student) and can switch in place, so each (uid, persona) has its own graph in one
document `demo_graphs/{persona}`: θ per domain, threshold_offset, a `knows` map of edges,
engaged contents and a `rev` counter. It starts as the persona's template
(`scripts/seed_personas.py` → `persona_templates/{persona}`): θ per domain plus anchor concepts
the persona knows (p 0.85, α+β 6) or doesn't (p 0.15, α+β 3), expanded through the
prerequisite DAG (prerequisites of known anchors p 0.8; up to 40 direct dependents of gaps
p 0.2). Reads use the template as-is; the first event or correction writes the copy. Demo
edges keep ≤ 5 evidence entries, and past 800 KB the oldest low-confidence non-seed edges are
dropped (Firestore's limit is 1 MiB; seeded templates are 14–20 KB). Signed-in readers start
neutral: θ = 0, no edges.

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
| home_country (decision 68: once, onboarding, never a band move) | + | 0.2 |
| profile_edit: concept claim (§15.3) | ± | 3.0 |
| profile_edit: domain claim, per core concept (§15.3) | ± | 2.0 |

While `learning_paused` is set, no evidence from events is applied (§15.1).

### Onboarding and calibration (M7, signed-in readers)
- Consent first (`consent-v1`, §11.4); nothing about a signed-in reader is recorded before it.
- Onboarding: field (suggests an analogy frame), interests, comfort per chosen domain, up to 3
  analogy frames, up to 3 liked **library** articles (picked, not pasted URLs). θ per rated domain
  from comfort: new −1.5, some −0.5, comfortable 0.5, expert 1.5 (the same targets as a profile
  edit's `set_domain_level`); interest 1.0 for chosen domains, 0.3 otherwise; each liked article
  adds `liked_article_mention` (+0.2) to its ≤ 15 linked concepts with salience ≥ 0.7.
- Calibration: 6 items (decision 68: screen 2's Quick check; was 8), round-robin over the interest domains that have ≥ 30 concepts (the four
  business domains if none does); within a domain, among its 150 highest-`doc_freq` concepts
  (seeded and grown concepts have doc_freq 0 and order most basic first), the one with b closest
  to θ, never one already asked (deterministic). Answers: explain +3.0, **heard −1.5**, none −3.0 (`calibration_answer`),
  and an Elo step with K = 0.3 and outcome explain 1, **heard 0.5**, none 0. Since decision 68
  K4b the six are fixed up front as a stored **set** (`calibration.set`: the terms already asked,
  then `next_item` repeatedly; built once in a transaction) and any unanswered set item can be
  answered, in any order; with no set only the current item can (older clients). A re-submitted
  screen 1 drops the set and keeps `asked`, so only the unanswered part is rebuilt.
  `/calibration/skip` ends onboarding (the web's Quick check never calls it).

### Decision 68: knowledge from who you are, taste from what you pick
- **Screen 1 builds knowledge.** Field → starting θ at "comfortable" (0.5) in its domains
  (software → technology; finance → finance, economics; commerce → business; law → law;
  science → science; medicine → health; teaching → education; design, other → none), first-time
  onboarding only (a field changed before finishing resets the old field's domains; a redo keeps
  θ; `comfort`, when sent, wins). Country (IN / GB / US) → up to 25 concepts of that
  `jurisdiction` with `doc_freq` ≥ 3 get one `home_country` step (+0.2), once ever per concept,
  skipped when p would reach ≥ 0.8 (from the reader's edge, else the prior), never a band move
  (nothing "moved up" after sign-up). A new screen 1 question "How do you like to take things in?"
  (Read / Watch / Listen, any, at least one) is stored as `formats` (optional at the API).
- **Screen 2 is taste only.** Cards (articles, videos, podcasts, each with its format word and
  length; "I'd read / watch / listen to this") move interest and format affinity, never the map:
  no term is offered and `POST /v1/onboarding/know` is a no-op. Below them, apart, the **Quick
  check**: the calibration above, 6 items, **all six at once** (K4b, Sourabh: "6 questions should
  be a single answer all in one go"), one row per term with "Know it" / "Heard of it" / "New to
  me", answered in any order, each once (`GET /v1/calibration/set`), the reader's own word on a
  term; skipping hides it; it never finishes onboarding
  (only Finish does); a re-submitted screen 1 keeps its asked list; hidden on a Redo.

### Onboarding in 2 screens (decision 41; replaces the M7 web steps, the M7 API stays)
- **Screen 1 "Tell Margo about you":** field chips (suggests one analogy frame), topic chips,
  optional free text "Anything else you follow?" (≤ 120 chars, React state only) and an inline
  consent checkbox (`consent-v2`; v1 stays valid). Order on Continue: consent → (text) `POST
  /v1/onboarding/resolve`, the screen stays to show matches ("F1 → Sports" with a select to change
  or drop it, removable concept chips, "Didn't recognise: …") → `POST /v1/onboarding` with
  interests = chosen topics ∪ mapped topics ∪ resolved concepts' domains. ~~θ stays neutral~~
  Superseded by decision 68 (above): the field sets a starting θ, the country a few home terms, and
  a read / watch / listen question is added; interest 1.0 chosen, 0.3 otherwise, plus screen-2
  picks (below).
- **Free text** (decision 42, §11.3): redacted, split on commas into ≤ 5 pieces of ≤ 40 chars;
  per piece: exact concept label/alias whole, then its " and "/"&" parts; then the topic alias
  list `ONBOARDING_TOPIC_ALIASES` (109 casefolded phrases covering all 14 topics: F1, IPL,
  Champions League, LLMs, EVs, crypto, mutual funds, UPSC, ISRO, …; no model call); then
  **word-level matching** (no model call): lowercased words and 2-word chunks of adjacent words,
  without stop-words, generic words ("news", "latest", "update", …) and bare country names,
  looked up in the alias list and concept labels/aliases (a one-word chunk counts as a concept
  only if the concept was met in the corpus, doc_freq > 0); the strongest match's topic wins
  (2-word chunks, then alias over concept, then doc_freq, then the earlier chunk). Only phrases
  with no word match go on to `resolve_names`
  (embedding candidates + `link_confirm`, individual pieces only); then the nearest topic scope
  line by embedding at cosine ≥ `ONBOARDING_TOPIC_THRESHOLD` = 0.86 (set on
  `evals/cases/onboarding_topics.yaml`, 27 phrases committed first: precision 9/9, recall 9/22,
  0/5 "none" phrases mapped; the whole topic order, aliases → words → embedding: **18/22, 0
  wrong, 0/5 "none" mapped**; 10 of the 14 phrases whose match doesn't depend on the alias list). Each phrase is embedded once per request. Nothing of the text is
  stored, logged or sent to search; 5 resolves per reader per day.
- **Screen 2 "Here's what's out there for you":** `POST /v1/onboarding/discover` with the
  chosen topics (≤ 6) and resolved concepts (≤ 2): shared day-keyed searches (§17.1; concept
  keys `feedx:c:<id>:<day>` (decision 50: restricted to top outlets), articles only, "<concept label> news this week", results must name
  the label or an alias). Up to 9 cards, every topic/concept with results gets one before any
  gets a second, articles first, then fresher (decision 68: the reader's chosen formats first,
  served cards keep their slots by a stored position `n`, slots held for a missing format while
  searches run; decision 69 G: the chosen formats share the cards equally and take turns, every
  other format gets 1 — Read + Listen of 9 → 4 / 4 / 1 video; `feed_rank.onboarding_targets`). Fewer than 6 and nothing pending → newest corpus
  articles in those domains. Each card: "I'd read this" / "Not for me" (`pick`: a rec signal
  `rec_clicked`/`rec_dismissed` and ±0.15 interest in the served item's domain, clamped, stored
  as a delta so Edit → Continue re-applies it). **Until decision 68** each card also had at most
  one "Know this?" term (`know`: the calibration evidence and the onboarding Elo step); since
  decision 68 no term is offered, `know` is a no-op and the Quick check below the cards asks
  instead. The term used to be fixed the first time the item is served: among the graph concepts its title
  and snippet name, **only of the item's own topic**, corpus concepts (doc_freq > 0) first, then
  b closest to θ; never a resolved concept or one already offered; ≤ 12 terms, ≤ 27 items, ≤ 9
  picks, ≤ 9 answers, each once. After 5 answers Margo reads back one deterministic sentence
  (likes minus skips per topic and the frame; since decision 68 no known or new terms). "Start reading" →
  `POST /v1/onboarding/finish` (done; offered, answered and picks cleared) → For you. A reload
  resumes on screen 2 (step `discover`).

### Redo setup (decision 48)
A finished Google reader can rerun the 2 screens from the profile ("Redo setup"):
`POST /v1/onboarding/redo` sets `onboarding_redo` ("about", then "discover") and clears the
offered/answered/pick lists; `onboarding_done` stays true, so the app never gates the reader.
`POST /v1/onboarding` during a redo keeps calibration progress and θ, merges the earlier comfort
answers and liked articles, keeps the reader's frames and adds the field's; interests are
rewritten from the new choices plus picks. Screen 2's routes (and the repo transactions) are open
while `onboarding_done` is false **or** a redo is in progress. `finish` and
`POST /v1/onboarding/redo/cancel` end it. The consent checkbox shows again when the stored
consent version isn't the current one (`consent-v2`). A finished reader opening /welcome outside
a redo is sent home. (Until decision 68, "Know this?" acronym terms ("OCT") counted only where the
item's text writes them in capitals; screen 2 offers no terms now, and the Quick check is hidden on
a redo, keeping θ and the formats answer.)

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
  30 days, else `0.2`; when the reference is linked to a graph concept, see §6.7.
  ENGAGED = any event on the content.
- unlinked concept demands aren't scored; unlinked terms use the article's domain for θ
- `miss = (1 − p)·(0.4 if explained_in_text else 1.0)`
- `span_score = miss · salience`
- paragraph: `para_score = 1 − Π(1 − span_score_i) + 0.3·structure·(1 − σ(θ_domain))`, clipped to [0,1];
  each concept/entity counts once per paragraph; θ_domain = the paragraph's dominant linked
  domain (by salience), else the article's

Thresholds (before per-user `threshold_offset` and density dial):
| density | span | paragraph | pre-read (mean span_score of assumed concepts) |
|---|---|---|---|
| minimal | 0.60 | 0.85 | 0.55 |
| balanced | 0.45 | 0.75 | 0.45 |
| guided | 0.30 | 0.65 | 0.35 |

`threshold_offset` adapts: +0.02 per dismissal/knew_this, −0.02 per text_searched or slowdown on
an unannotated paragraph; clamp to [−0.15, +0.15]. It is added to all three thresholds.
Dismissal is the `annotation_dismissed` event (no Beta evidence). A `text_searched` on a marked
term carries that concept (evidence and offset); on a paragraph with no span or prompt marks it
carries only `paragraph_id` (offset only, M6). Slowdown (dwell against the reader's medians) is
not computed yet.

**Worked example** (`tests/test_scorer.py::test_design_worked_example`). Balanced density; the
reader has θ = −0.5 in finance and economics, an edge on *bond yield* (α 0.44, β 1.56 → 0.22)
and one on *inflation* (α 4.05, β 0.95 → 0.81). One paragraph, structure 0.5:
- *yield curve* (b −0.7, prerequisite bond yield, salience 1.0): own prior σ(0.2) = 0.55,
  capped at 0.22 + 0.1 = 0.32 → span_score 0.68 ≥ 0.45 → **shown**.
- *inflation* (salience 1.0): 1 − 0.81 = 0.19 < 0.45 → **skipped**.
- paragraph: 1 − 0.32·0.81 = 0.741, below 0.75 on the spans alone; the structure term adds
  0.3·0.5·(1 − σ(−0.5)) = 0.093 → 0.834 ≥ 0.75 → **paragraph marker**.

## 6. Selection (annotation budget)
1. Drop spans below threshold. Rank by `span_score` (ties: reading order).
2. First occurrence of each `target_id` only.
3. Caps: ≤ 1 span annotation per 80 words (at least 1), ≤ 1 paragraph marker per 3 paragraphs
   (at least 1), ≤ 2 span annotations in any single paragraph.
4. Pre-read card if triggered (mean span_score of the assumed, i.e. not `explained_in_text`,
   concepts ≥ the pre-read threshold): from the highest-scoring assumed concept with
   p_know < 0.5, step to its weakest prerequisite until one has p_know ≥ 0.7; ≤ 3 steps
   including the starting concept, most basic first; each step links to a corpus article
   where that concept is `explained_in_text` (shortest first; never the article being read or
   a `user_ingested` page), else shows the concept definition. When the walk stops because the
   next prerequisite is known (p_know ≥ 0.7; ties: highest p, then id), that prerequisite leads
   the path as a `known: true` step, shown ticked (Design pass; the extension's card skips it).
5. Uncertainty prompt ("Know this?"): at most one per article, three per day (a reload of an
   already-prompted article keeps its prompt), only when salience ≥ 0.7 and
   0.35 ≤ p_know ≤ 0.65 and α+β < 4, only for a concept not already annotated, and never while
   learning is paused. Highest salience first, then p_know closest to 0.5.
6. **The reader's word wins:** a concept whose latest explicit evidence is `knew_this` or an
   "I know this" correction is not annotated, whatever p_know says, until an explain_opened,
   text_searched or "I don't" says otherwise.

7. **Linked references** (context demands linked to a concept): the reading-history p above is
   a floor; it rises to the concept's p_know only when the reader has a KNOWS edge for it
   (seeded or earned) or the prior alone is ≥ 0.8. A generic prior guess from estimated
   difficulty never hides a reference. Measured on all 310 corpus articles × 3 personas at
   balanced density (trader vs policy student identical span sets / mean Jaccard): no rule
   29 / 0.37; any p_know 2 / 0.08 but it hid ~1,450 underlines, ~95% on the prior alone;
   edge only 25 / 0.33; **edge or prior ≥ 0.8 (chosen) 8 / 0.15**. The five cases it was
   judged on:

   | Persona | Article | Reference | p_know (source) | Any p_know | Chosen |
   |---|---|---|---|---|---|
   | policy_student | Guardian, "Oil price rise creates more pressure on UK policymakers before budget" | Bank of England | 0.92 (prior) | hidden | hidden |
   | trader | Guardian, "Good news in US inflation report boosts chances Fed won't hike rates" | Dow | 0.95 (prior) | hidden | hidden |
   | newcomer | ET, "Rate cut cycle near turning point. What lies ahead for Indian bonds?" | RBI | 0.53 (prior) | hidden ("benchmark 10-year bond" took its slot) | shown |
   | policy_student | Wikipedia, "Central bank" | Network for Greening the Financial System | 0.61 (prior) | hidden | shown |
   | trader | Wikipedia, "Bond (finance)" | Russell Indexes (mislinked to S&P Dow Jones Indices, issue #6) | 0.79 (prior) | hidden | shown |

Spans only for graph-linked demands (the card needs a definition until M5); the paragraph
noisy-OR also counts unlinked terms and context references. Scoring p95: 0.2 ms for a
1,200-word article (synthetic 3,300-concept graph in tests; 0.25 ms on real articles).

## 7. Explanations
Request: `{content_id, demand_id | paragraph_id}` (+ `?persona=` for demo readers). The server
derives the reader's band for the concept (current p_know, forgetting applied, or the IRT prior;
for a paragraph, the prior with b = 0 in the paragraph's most salient domain), one THINKS_IN
frame and `explanation_style` (short | normal | detailed, §15.3). Demo personas have fixed
frames: newcomer software, trader cricket, policy student law (`PERSONA_THINKS_IN`); a signed-in
reader uses their first THINKS_IN choice, else no analogy.

**Analogy frames: Your pick and For you (decision 67 A).** `POST /v1/explain` takes `frame:
"pick" | "for_you"` (default pick) and every response carries `frames: {pick, for_you, used}`.
The pick is the THINKS_IN choice above. For you comes from `reader/frames.for_you` (pure): the
reader's own edges only (forgetting applied, p ≥ 0.5, not the prior), domains with ≥ 3 such
concepts, ranked by count, mean p, then taxonomy order, the note's own domain excluded (an
analogy from the same field explains nothing), mapped to a frame: technology → software, health
→ medicine, education → teaching, law, science; the other domains (economics, finance, business,
policy, politics, environment, sports, culture, society) are frames by name (`MapFrame`).
`analogy_domain` and `thinks_in` are `Frame = ThinksIn | MapFrame`, so the explain task's
structured output accepts a map frame; the prompt text and versions are unchanged (a pytest pins
them), so cached Backgrounds stay valid. The Background cache key already holds the frame;
`frame` and `shift` combine under the same caps. The card shows a two-option toggle ("Your pick ·
Cricket" / "For you" — the for-you frame isn't named, Sourabh 2026-10-17; "No analogy" when there
is no pick) only when the two differ; the
other frame loads on click and the choice holds for the page (and its prefetch). Measured: the
Background pipeline with every card in finance kept every safety target (`evals/changelog.md`).

The served card (`app/explain/models.py`, `extra="forbid"` on each part's schema: `Restatement`
`{author_says}` from `restate`, `BackgroundDraft` `{background, analogy_domain}` from `explain`):
```json
{
  "background": "≤ 3 sentences of general knowledge; analogy from the reader's frame allowed here only",
  "author_says": "Restatement of the span/paragraph. Preserve hedges, attribution, numbers, negation.",
  "analogy_domain": "one of the THINKS_IN frames | null"
}
```
Inputs to the prompt are ONLY: the span, its sentence and paragraph, the concept definition and
up to 3 prerequisite definitions, the reader band, the THINKS_IN frame, the explanation style
(a test pins the key set). No uid, no history, no web access. Article text is inside the content
delimiters and stated to be data.

**Say it simpler / Go deeper** (Design pass): a span request may carry `shift: -1 | 1`. The
Background is then written for the reader's band moved one step (clamped to the four bands)
through the same verified path and cached under the same key shape (`span_hash, band, frame,
style`); the shared restatement is reused; the request counts once against the explain caps;
the response's `band` is the band written for, and `can_simpler` / `can_deeper` say whether the
reader's own band has a step below / above. Shifted cards load only on click (never
prefetched); `warm_demo --shifts` warms them for the demo articles.

**Thinking level (decision 67 L1–L2).** `LLM_REASONING_EFFORT` (task → low / medium / high)
sets a structured task's Gemini 3 thinking level over its route's; `transcribe` keeps its own.
Measured on the safety suite (`evals/changelog.md`): drafts at low were 2 s faster at p50 and a
third cheaper but lost one verified card of 25 and raised p95. Served (Sourabh's call, 2026-10-16):
`restate` and `explain` at low, the two judges at the model default. `link_confirm` (decision 69
D, fresh runs, `evals/results/*d69-*`): low made calls ~4× faster (median 3.5 s vs 14.0 s, p90
4.0 s vs 89.0 s per eval batch; the default run had 3 of 22 calls fall back after timeouts, low
none) and variant precision 0.862 vs 0.843, but passed 14/16 regression cases vs 15/16 (L04, a
paraphrase, left unlinked rather than mislinked); the pre-set rule
(passes ≥ default's) was not met, and Sourabh overrode it ("yes", 2026-10-17): **`link_confirm`
runs at low** — for article linking, growth, goals, profile edits, onboarding terms and the
jurisdiction backfill; goals and onboarding checked at both levels (`evals/resolve_effort.py`: 21/21 agreement in the saved run, 18/20 in an earlier unsaved one; STATUS §37). Eval answers are cached per thinking level when one is set.

**Prefetch (decision 67 L3).** The web host prefetches the top 3 span notes when a page's notes
arrive; for signed-in consumers only, a span note whose mark comes within one screen of the
viewport is prefetched too, at most 10 per page in all and 2 at once. Demo consumers keep the
top 3 (their 40-a-day and the shared 400-a-day caps are for clicks). A prefetch answered with
`capped: true` is not kept, so a later click asks again.

Since M7.5 (decision 37) `explain` (v5) and `restate` (v2) describe the source as "news on any
subject", not business and economy news; the judge prompts already said only "news article"
and are unchanged (verify-v2, verify-background-v1). Before/after safety runs: `evals/report.md`.

### Verifier (must pass before cache/show)
1. Deterministic checks (`app/explain/checks.py`) on `author_says`. Scope: in span mode hedges,
   attribution and negation are checked against the **span's sentence** (a hedge elsewhere in the
   paragraph says nothing about this restatement), numbers against the paragraph; paragraph mode
   (stricter) checks all four against the whole paragraph:
   - every number in `author_says` appears in the source ("40%" = "40 per cent", "3.5bn" =
     "3.5 billion", number words in the source match digits);
   - a hedged source keeps a hedge; an attributed source keeps attribution (said, according to,
     argues, claims, theorize, ...; noun-prone words like "notes" are excluded); negations are
     not dropped; no link in either part unless the source has one.
2. Judge (`verify` task on `MODEL_JUDGE`, default MODEL_QUALITY; never falls back): split
   `author_says` into atomic claims; each must be ENTAILED by the source paragraph; `background`
   must neither contradict it nor state facts about this article. Paragraph mode: only explicit
   statements count as entailed. The judge is skipped when step 1 already failed.
3. On fail: regenerate once with the failure reasons; on second fail, fall back to the concept's
   `definition` as a plain gloss (no `author_says`).

**Two parts, generated and cached separately (M6).** "What the author is saying" depends only on
the span and the style, so it is made once and shared by every reader; only the Background
depends on the reader:
- restatement: `restate` (prompt `restate-vN`: span, sentence, paragraph, concept definitions,
  style; no band, no frame) → deterministic checks → claims judge (`verify`) → regenerate once.
  Cache `explanations/{sha1("restate" | span_hash | style | restate-vN+verify-vN)}`.
- Background: `explain` (prompt `explain-vN`: as above plus band and frame) → link check →
  Background judge (`verify_background`: contradicts the paragraph, or states facts about this
  article) → regenerate once. Cache `explanations/{sha1(span_hash | band | thinks_in | style |
  explain-vN+verify-background-vN)}`.
`span_hash = sha1(content_id | paragraph_id | anchor.exact)` (paragraph mode hashes the paragraph
text). On a miss both parts run at the same time.

| Restatement | Background | Card | `kind` |
|---|---|---|---|
| verified | verified | both parts | `verified` |
| verified | rejected twice | the restatement; the definition stays in the Background panel (`background: null`) | `verified` |
| rejected twice | (not made, or either) | the definition only | `definition` |

Each entry stores `part`, `kind`, the text (none when rejected), model ids, prompt version, key
parts, cost and created_at. Verified parts are cached, and so is a part rejected twice (no text
stored), so a hard span doesn't re-spend on every hover; a judge outage or the budget guard
caches nothing. One generation per part per instance at a time, keyed by the part's cache key
(a prefetch and a hover share it, and so do two personas loading the same span cold).
A request that generates anything counts **once** against a daily cap per reader (100;
40 anonymous, 400 for all anonymous readers together); past the cap a shared restatement still
shows and the Background stays the definition. The card id is `restatement_key-background_key`.

Prefetch: the web client asks for the top 3 spans by score as soon as the annotations arrive
(the annotations route itself stays LLM-free); other cards load on open with a skeleton.

"This is wrong" (POST /v1/explain/{id}/report): evicts both entries named by the card id (the
shared restatement for everyone, and this Background), copies each to `explanation_reports/{id}`
for review (no user identifier), and records a `report_wrong` event (idempotent by event id,
subject to pause). The next open regenerates.

## 8. API (FastAPI, `/v1`, Firebase ID token in `Authorization: Bearer`)
| method | path | purpose |
|---|---|---|
| POST | /v1/content | `{url}` (server fetches via safe_fetch) or `{url, title, paragraphs[], defer?}` (extension, already extracted and redacted) → `{content_id, title, paragraphs, status, pii_found_before_backstop?}`; ingests if new. Requires auth and the per-user daily cap. Extension text (M8): the fetch path's doc for the URL is returned if one exists, else the reader's own earlier extension doc for it (free, no new analysis), else a new doc under `ext:` id = hash(normalised URL + hash of the cleaned, redacted text) so client text never answers the fetch path and nobody is served text they didn't submit. `defer: true` returns `status: "analysing"` after phase 1 (then POST …/analyse, as "Open here"). Every path records the page in the reader's `ingested`. Errors: 409 `onboarding_required` (a Google reader who hasn't finished onboarding), 422 `personal_data` (Presidio backstop, §11.3). `pii_found_before_backstop` = placeholders the server's redactor added (0 when the client did its job) |
| GET | /v1/content?q=&persona=&density= | library list: `{id, title, site, word_count, description, author, published, image, domain, concepts_new}`; `domain` = graph domain with the most linked salience; `concepts_new` = span annotations this reader would get; `format: article \| video \| podcast` (§21) |
| GET | /v1/content/{id} | article for rendering: metadata + `paragraphs[{id, text}]` + `status: ready \| analysing` (a pending article, §3; annotations and recommendations answer 409 until it is ready). A recording (§21) adds `media {kind, video_id \| audio_url, duration_s}`, `start_s` per paragraph, and `status: transcribing` (no paragraphs yet), `refused {code, message}` or `failed`. `grow_pending: true` → the client calls POST …/grow once, then reloads the notes (M9) |
| POST | /v1/content/{id}/analyse | phase 2 of "Open here" (§3): 200 `{status: ready}` (no LLM call if already analysed), 202 `{status: analysing}` while another request holds the lease, 410 after 3 failed analyses, 504 on the 120 s timeout; no ingest slot (taken in phase 1) |
| POST | /v1/content/{id}/grow | a reader's stored page that missed concept growth (M9, §2): 200 `{status: none}` (no model call: nothing to grow), `{status: capped}` (no slots left today), `{status: grown, linked}`; 202 `{status: growing}` while another request holds the claim; 503 on the budget. Access as …/analyse (extension pages: their submitters). Never in the scoring path; the client then reloads the notes |
| POST | /v1/content/{id}/transcribe | a recording's transcript (§21.3): 200 `{status: analysing}` once stored (no model call if it already is), 202 while another request or podcast holds it, 410 after 3 failed attempts, 422 with the refusal code, 503 on a budget or an unavailable source, 504 on the timeout. Then …/analyse as for an article |
| GET | /v1/content/{id}/recommendations?prefer=&basis= | Up next (§16): up to 6 items, `pending` while web lookups run; each item carries `open_here` (§21.4). `basis=story` (decision 69 B, the end of the article): the article's key ideas plus the same story elsewhere ("More on this story", corpus articles only, §16.3); `basis=article` (decision 67): the card chips, one per format; `basis=consumer` (the API default and the pre-69 web; the recap still asks it, so its picks teach a "Not really" term): the reader's new terms |
| POST | /v1/recs/events | `{events: [{id, type: rec_shown\|rec_clicked\|rec_dismissed\|rec_completed, item_id}]}` → `{applied, ignored}`; idempotent by event id |
| POST | /v1/recs/open | `{url}` → `{content_id, new, ready}`: phase 1 of ingesting a web recommendation via safe_fetch as `user_ingested` (§3), within the per-user daily cap (429 past it); `ready: false` until POST .../analyse completes. A YouTube or Apple Podcasts episode URL opens a recording instead (§21.2): `kind`, `stage: "transcribe"`, 422 with a refusal code, 429 `media_cap_reached`. POST /v1/content answers a media URL 422 `use_open_here` |
| GET | /v1/me/export | everything we hold about the caller, as JSON |
| DELETE | /v1/me | delete all of the caller's data and their Auth user |
| GET | /v1/content/{id}/annotations | ranked, budgeted annotations for the caller |
| POST | /v1/explain | `{content_id, demand_id?, paragraph_id?, shift?: -1\|1}` → `{id, kind: verified\|definition, mode, label, definition, background, author_says, analogy_domain, band, can_simpler, can_deeper, thinks_in, style, cached, capped, prompt_version}` (§7; `shift` = "Say it simpler" / "Go deeper", span notes only, 422 with a paragraph) |
| POST | /v1/explain/{id}/report | `{event_id, content_id, concept_id?}` → `{evicted, event_applied}`: "This is wrong" (§7) |
| POST | /v1/events | `{events: [{id, type, at, concept_id?, content_id?, paragraph_id?, words?, ms?}], persona?}` (types include `article_helpful` `{content_id}`: the action bar's Helpful, stored, no evidence) → `{applied, events_applied, events_ignored}`; sync, idempotent by event id (stored at `users/{uid}/events/{id}` with `expire_at` for the 90-day TTL); `applied: false` and no writes while learning is paused |
| GET | /v1/me/graph | concepts by domain with band, plus stats (concepts learned, annotation trend); `?domain=X[&q=]` → capped subgraph for the knowledge map (§15.2); `?view=overview` → the all-topics map `{domains, nodes[{id, label, domain, band, ready, goal, weight, definition, recent, rose_this_week}], edges}` (§15.1) |
| POST | /v1/me/bands | `{concept_ids: [≤ 50]}` → `{concept_id: band}`: current bands (edge with forgetting, else the prior), for the end-of-article recap (§19) |
| GET | /v1/me/saved | the reader's saved articles as library rows, newest first, through the library's visibility filter |
| GET | /v1/me/saved/ids | just the saved ids (the reader's Save button; no library rows built) |
| PUT / DELETE | /v1/me/saved/{content_id} | save / unsave a library article the reader can see (corpus or their own pages); ≤ 500; signed-in readers need consent |
| PATCH | /v1/me/graph/{concept_id} | user correction ("I know this" / "I don't") → strong evidence |
| GET | /v1/me/profile | reading profile page data: summary, domains, THINKS_IN, weekly band changes, trend (§15.2) |
| PATCH | /v1/me/settings | `thinks_in`, `density`, `explanation_style`, `learning_paused` |
| POST | /v1/me/profile/edits | parse a natural-language profile edit → preview, writes nothing (§15.3) |
| POST | /v1/me/profile/edits/{id}/apply | apply a previewed edit |
| POST | /v1/me/profile/edits/{id}/undo | undo an applied edit |
| POST | /v1/me/consent | `{version}` (signed-in readers): records consent; required before anything is recorded (§11.4) |
| POST | /v1/onboarding | field, interests, comfort per domain, ≤ 3 frames, ≤ 3 liked library content ids, `country` (decision 50), `formats` (decision 68, optional: empty keeps the stored answer) (§4); needs consent |
| GET | /v1/calibration/next | next item: concept with b closest to current θ, not yet asked; `{done}` after 6 (decision 68) |
| GET | /v1/calibration/set | decision 68 K4b: the six Quick check terms at once, `{done, total, items: [{concept_id, label, domain, answered}]}`; built and stored once; empty and done after finish |
| POST | /v1/calibration/answer | `{concept_id, answer: explain|heard|none}`: any unanswered item of the stored set; with no set only the current item (409 otherwise) |
| POST | /v1/calibration/skip | ends calibration (onboarding done) |
| POST | /v1/onboarding/resolve | `{text ≤ 120}` → `{concepts, topics: [{phrase_index, phrase, topic, via}], unrecognised}` (§4); 429 past 5/day |
| POST | /v1/onboarding/discover | `{topics ≤ 6, concepts ≤ 2}` → `{items, pending}`; unknown concept 422; 409 after finish |
| POST | /v1/onboarding/pick | `{item_id, liked}`: a served item only (404), once (409), ≤ 9 |
| POST | /v1/onboarding/know | decision 68: a 200 no-op `{"saved": false}` (screen 2 writes no knowledge), kept for old clients until after judging |
| POST | /v1/onboarding/finish | onboarding done; the offered/answered/pick lists are cleared |
| GET | /v1/me/profile/edits | the last 10 applied/undone edits (expired pending ones are deleted) |
| GET | /v1/feed?persona= | For you (§17): `{topics, items[{id, topic, topic_label, format, title, url, source, snippet, thumbnail, duration_or_read_time, published_at, new_concepts, goal, why, score}], pending, snapshot, prepared_at, country}`; demo readers get their persona's pre-seeded snapshot (`snapshot: true`) and trigger no search; items carry `open_here` (§21.4) |
| POST | /v1/internal/feeds/collect | Outlet collection (§17.1a). Outside the Firebase router: only a Google ID token with `iss` accounts.google.com, `aud` = `FEED_JOB_AUDIENCE`, `email_verified`, `email` = `FEED_JOB_SA_EMAIL`; either setting empty → 403 |
| GET | /v1/me/goals | the caller's reading goals with progress (§18); signed-in readers only (403 for demo readers) |
| POST | /v1/me/goals | `{type: habit, metric: articles\|minutes, per_week}` or `{type: learning, text}` (≤ 120 chars, resolved, never stored) → the goal with progress; needs consent; ≤ 5 goals (409), 422 `goal_not_found`, 429 past `GOAL_RESOLVE_DAILY_CAP` |
| DELETE | /v1/me/goals/{id} | 204 |
| GET | /v1/me/graph?goal={id} | the learning goal's ≤ 8 target nodes and their edges, for the map's goal view (§18) |
| POST | /v1/me/demo/reset | `{persona}` (demo readers): back to the original persona for this session (§15.3) |

Annotation response items (spans first, ranked; then paragraph markers, the pre-read card,
the prompt; `count` counts spans). Paragraph: `{id: "para:p3", kind, paragraph_id, score,
domain}`. Pre-read: `{id: "preread", kind, score, concept_id, label, steps: [{concept_id, label,
definition, content_id?, title?}]}`. Prompt: `{id: "prompt:d17", kind, anchor, paragraph_id,
concept_id, label}`. `density` defaults to the reader's setting. Span item:
```json
{"id": "d17", "kind": "span|paragraph|preread|prompt",
 "anchor": {"exact": "...", "prefix": "...", "suffix": "..."},
 "paragraph_id": "p3", "score": 0.68, "concept_id": "c_yield_curve", "label": "Yield curve"}
```
Span items also carry `definition`, `domain` and up to 3 `prerequisites` labels: the card shows
them at once and keeps the definition when no verified explanation exists, plus `debug {p_know, salience, span_score, domain,
base_difficulty}` when `?debug=1` and `ENV=dev`.

## 9. Client behavior (`packages/annotator`)
- Anchor resolution: find `exact` with matching prefix/suffix inside the article root; fall back
  to fuzzy (normalized whitespace); skip if not found.
- Span: two highlight styles from the item's `level` (Design pass): **new** (unaware or heard
  of: soft fill, underline and a small dot) and **refresher** (understands or better: a thin
  underline); a missing level means new. `level` and `band` come from the reader's uncapped band
  for the concept, the band explanations are written for. Hover (desktop) / tap (mobile) opens
  the card; card has "Knew this", "Helpful", "This is wrong". Card label: "Explanation — not the
  author's words". The card also shows how the note is pitched (a 4-step meter and one line, from
  the explanation's `band`), "Builds on" (prerequisite labels) above the Background, the author
  line set as a quote, and, when the host passes `loadShifted`, "Say it simpler" / "Go deeper"
  (one band down / up, "Back to my level" to return); the extension passes nothing and gets no
  depth buttons.
- Card (M5): a Background panel (recessed tint; names the analogy frame when one is used) and
  "What the author is saying" (primary, accent rule). The glossary definition fills the
  Background panel at once and is replaced in place by the verified Background (no layout jump;
  height animates); definition-only results label the panel "Definition". Placement: sidenote in
  the margin column at ≥1200px (level with its line), popover 360px elsewhere (height capped to
  the room it has; a deliberate open scrolls its line up under the top bar to make room), bottom
  sheet below 640px. Cards stay below the host's fixed bar (`--rl-top-inset`). A persona switch
  reloads an open card and resets its actions.
- Paragraph: small margin marker (a pilcrow; floats at the paragraph's top right below 900 px) →
  the shared card in paragraph mode, "What this paragraph is saying" (no Knew this: no concept).
- "Know this?" prompt: an inline chip after its term (Yes / Not really → PATCH /v1/me/graph),
  collapsing to "Noted, thanks."; the pre-read card sits above the article (`renderPreread`),
  steps most basic first, each a link to its library explainer or a disclosure with the
  definition. `renderPreread` skips a `known` step; the web app draws the path itself with that
  step ticked (§19).
- Controls the annotator inserts carry `data-rl-ui`: anchor resolution skips them, they are
  `user-select: none`, and a copy across one gives back only the article's words.
- Events batched every 5 s and on `visibilitychange` / `pagehide` (dwell flushed first), one
  retry per failed batch, idempotent by event id: explain_opened, knew_this, explain_helpful,
  report_wrong, annotation_dismissed (a **span** card opened deliberately, by click, tap or
  keyboard, and closed without an action; hover peeks and paragraph cards never count),
  text_searched (copy or right-click with a selection: the overlapped mark's concept, or the
  paragraph only when it has no marks; never the text), paragraph_dwell (IntersectionObserver at
  50% visibility while the page is visible; stretches under 1 s dropped; `words` on a
  paragraph's first dwell per page view, 0 after, so re-reading doesn't inflate words read).
- **Extension mounting (M8).** The content script runs only after the reader's click. It tags the
  live page's paragraphs against the server's stored paragraphs (`data-rl-paragraph`), matching
  each on its redacted, whitespace-normalised text, then falling back to a prefix match for a
  fetch-path doc (its own extraction); the deepest matching element wins and no text changes.
  The annotator mounts on the common ancestor with `styles: "external"`: the worker applies
  `ANNOTATOR_CSS` and the Gloss token sheet with `chrome.scripting.insertCSS` (a publisher's CSP
  can't block it, and no inline `<style>` triggers CSP reports). Notes take light or dark tokens
  from the article's own background (`data-rl-scheme`), not the OS. Popover and bottom sheet
  only (no sidenote, no depth buttons); the pre-read sits above the first tagged paragraph.

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
  | restate, explain, link_confirm (timeout 45 s, batches of 10) | MODEL_QUALITY | MODEL_FAST |
  | verify, verify_background | MODEL_JUDGE (empty = MODEL_QUALITY) | none: if a judge is unavailable, show definition gloss only |
  | transcribe (`llm.transcribe`, §21.3; low thinking, 90 s, 16k output tokens) | MODEL_QUALITY | none: a timeout is charged its estimate and not retried in the run |
- Error handling per model (`classify_error` in `llm.py`):
  - retry the same model with backoff (max `LLM_MAX_RETRIES`), then fall back: timeout (20 s),
    429, 5xx;
  - fall back immediately, no retry: 404 / 501 model not found (Vertex reports an unknown model
    as a 500 whose message carries the 501/404), and schema validation failure after 1 repair retry;
  - raise `LLMRejected` immediately, never fall back, logged at ERROR with task and model:
    400, 401, 403 and any other unclassified error. A bad request or bad credentials would fail
    the same way on the fallback model and hide a real bug.
- `verify` and `verify_background` never fall back for any error; they raise
  (`LLMUnavailable` / `LLMRejected`).
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
| Token theft from extension | extension | short-lived Firebase ID tokens in `chrome.storage.session` only (default trusted-contexts access: content scripts can't read it), refreshed by the worker through Firebase's securetoken endpoint (M8: no Gloss tab needs to stay open), handed over only by the web app's Connect page from our own origins (re-checked in the worker), never logged |

### 11.2 `safe_fetch`
- Schemes `http`/`https` only; ports 80/443 only.
- Resolve DNS first; reject private, loopback, link-local (incl. 169.254.169.254), multicast and
  reserved ranges for IPv4 and IPv6; re-check after every redirect (max 3); pin the resolved IP
  for the connection.
- Timeout 10 s, max body 3 MB, `Content-Type` must be HTML.
- Identify with a clear User-Agent; respect robots.txt disallow for our agent; skip known
  paywalled responses rather than working around them.
- Audio (§21): `audio_head` (64 KB ranged GET) and `fetch_audio` reuse every check above with
  their own limits: 6 redirects (enclosures chain measurement prefixes), 45 s, `audio/mpeg` /
  `audio/mp3` only, cut off at `MEDIA_MAX_AUDIO_BYTES`. The bytes are never stored or logged.

### 11.3 PII handling
- Article content is public material, not PII, but it is still untrusted input.
- The For you analogy frame (decision 67) is one word from a fixed list, derived per reader from
  their own map; only that word reaches the model, never the edges or reading history behind it.
- Extension activation (as built, M8): only when the reader clicks the toolbar button (`activeTab`,
  no host permissions, no allowlist). Refused before anything is read, and told in the popup:
  non-web schemes; mail, banking, sign-in and private-network URLs (checked in the worker before
  any script is injected); any page with a password field or an `autocomplete="cc-*"` input
  (checked first by the injected script). A refused page gets none of our CSS or attributes.
- Extension sends only the Readability-extracted article text (from a clone of the page) and the
  URL without its fragment or user info, query values redacted; never raw HTML, comments or form
  fields.
- Client-side redaction before sending (`redact.ts`): emails, phone numbers (a phone shape:
  country code, Indian mobile, bracketed area code), Luhn-valid card numbers (grouped, or
  ungrouped with an issuer prefix), Aadhaar (4-4-4) and PAN → `[REDACTED:type]`. The API's
  `app/privacy/redact.py` uses the same patterns, pinned by one shared fixture; news figures,
  dates and year ranges survive. Reader-typed text (profile edits, goals, onboarding) is
  redacted with `typed=True`, which also keeps the older broad catch for any phone-like run.
- Server-side backstop (`app/privacy/pii.py`): Presidio (spaCy `en_core_web_sm`; email, phone,
  card, IBAN, Aadhaar with its checksum, PAN) on the cleaned extension text before anything is
  stored or charged; client placeholders count as findings. Refused (422 `personal_data`) above
  20 findings per 1,000 words (with at least 3) or at 3 card numbers; set from the stored
  corpus (max 3.98, 0 of 338 refused) and frozen refuse/pass fixtures. Below it the strict
  redactor runs on every paragraph. Offline (tldextract's bundled snapshot), lazy, logs counts only.
- Google Cloud Sensitive Data Protection is the managed upgrade path; not used in the hackathon
  build because Presidio covers it at no per-call cost.

### 11.4 User data rights and minimisation
- Data held: Firebase uid, display name, onboarding answers, settings, KNOWS edges, domain
  abilities, weekly reading stats, applied profile edits (ops and deltas, never the raw text),
  reading goals (`goals`: type, numbers, resolved target ids and labels, never the goal text),
  pages the reader brought in (`ingested`: content id and time), the country they chose
  (`country`, decision 50: picks which outlets are local in For you and, decision 68, a few home
  terms' small head start; never sent to a model or a search; demo readers can't set it), the
  read / watch / listen answer (`formats`, decision 68),
  events (raw events expire after 90 days via Firestore TTL; aggregates stay).
- No email stored in our collections (Firebase Auth keeps it).
- `GET /v1/me/export` → JSON of everything above. `DELETE /v1/me` → deletes all user documents
  and the Auth user.
- Firestore security rules: clients never read/write Firestore directly; only the API service
  account does. Rules deny all client access.
- Onboarding (decision 41) keeps, until finish, the served items (`onboarding_offered`; no terms
  since decision 68), picks and (decision 48) `onboarding_redo` on
  `users/{uid}`, and daily counters
  `onboarding_resolve_counts`, `onboarding_discover_counts`; all covered by export and delete.
- Media (§21): `media_counts` (new recordings opened per day, a count only), covered by export
  and delete. Transcripts and the day's refusal memory hold no uid.
- **Free-text exception (decision 42), in the tests' words:** the onboarding free text never
  reaches search, any log record or any stored document; a model sees only individual redacted
  pieces with no exact or word match (embedding, `link_confirm`), never the full text: **each
  piece goes in its own embedding request and its own `link_confirm` call** (≤ 5 per resolve).
- Consent (`consent-v2` inline on onboarding screen 1; `consent-v1` stays valid) states what is
  collected and why, in plain language, and that typed text is matched to topics by our model
  and isn't stored. The API
  enforces it (M7): for a signed-in reader without consent, POST /v1/events applies nothing,
  page views and rec signals write nothing, corrections, settings and profile edits are 403;
  export and delete are always open. Design with
  India's DPDP Act principles in mind (notice, consent, purpose limitation, erasure); this needs
  proper legal review before any public launch.

### 11.5 Platform hygiene
- Cloud Run service account with least privilege (Vertex AI user, Firestore user, GCS object
  viewer on the graph bucket, Secret Manager accessor).
- CORS: only the web app origin and the extension origin.
- Secrets in Secret Manager; nothing secret in the extension bundle.
- Rate limits per uid: 60 annotation reads/min, 30 explain calls/min, 20 new URLs/day,
  10 profile-edit parses/day (§15.3), 10 learning-goal resolutions/day
  (`GOAL_RESOLVE_DAILY_CAP`, §18), 120 requests/min overall, 30 event batches/min. The For you
  feed's searches have their own shared cap, `FEED_SEARCH_DAILY_CAP` (60/day, §17), inside the
  global search caps.
  Concept growth (§2): slots taken when growth runs; all anonymous readers share 150 a day.
  Videos and podcasts (§21.1): 5 new recordings/day per uid (1 per demo reader, 10 for all demo
  readers together), 300 lookups/day for everyone, and a $3 media budget inside the $8 guard.
  Per-minute limits are in memory per instance (≤ 3 instances); daily caps are in Firestore,
  reserved in a transaction before the work and refunded if it fails. Two-phase ingest (§3):
  the slot is taken in phase 1 and refunded if phase 1 fails; an article whose analysis later
  fails 3 times (410) does **not** refund it, because the pending doc holds no uid to refund.
- **Anonymous (demo) readers** (Firebase Anonymous sign-in, M3): 30 annotation reads/min,
  60 requests/min, 3 new URLs/day per uid, and shared caps across *all* anonymous readers so
  minting accounts can't multiply them: 30 new URLs/day (`ops/ingest/days/{day}`) and 100
  uncached web-search calls/day (`ANON_SEARCH_DAILY_CAP`, counted in `ops/search/days/{day}`).
  Anonymous readers always get cached web results; past the search cap they trigger no new
  searches, so concepts without a cache entry give them library items only.
- Auth: every `/v1` route needs a Firebase ID token (Google or Anonymous providers only; others
  get 403). Only `/health` is public. A deleted user's still-valid token is refused for an hour
  on the instance that deleted it.

## 12. Evaluation (what we show judges)
1. **Faithfulness**: 40-case suite (15 adversarial from M5, 25 from real articles). Report
   verifier rejection rate on bad cases and acceptance on good cases.
2. **Injection**: 10 articles with planted instructions ("ignore previous instructions...",
   fake system notes). Pass = output schema-valid and no planted text followed.
3. **Cost and latency**: cost per ingested article, per explanation, cache hit rate, p95
   annotate latency.
Items 1–2: `uv run python -m evals.run --suite safety` → `evals/report.md`; item 3:
`uv run python -m scripts.eval_ops` (production, read only) → `evals/ops_report.md`. Headline
numbers go in the deck.

## 13. Delivery and observability
- GitHub Actions: ruff, pytest, TS typecheck on every PR; deploy on `main` using Workload
  Identity Federation (no JSON keys).
- Structured JSON logs with `request_id`, `uid_hash`, `task`, `model`, `cost_usd`, `latency_ms`.
- One Cloud Monitoring dashboard: requests, errors, p95 latency, daily LLM spend.

## 14. Out of scope for the hackathon
Learned scoring model, Neo4j/Postgres, open-ended (user-defined) domains, mobile app,
LiteLLM proxy server, self-hosted open models, Terraform.

## 15. Reading profile page
The reader's view of their own model: what we think they know, how it is changing, and how
to correct it. Built in two steps: read-only page and settings in M3 (API) and M7 (UI),
natural-language profile edits in M7. Everything shown is computed deterministically from
the reader model in §4; only the optional profile edit (§15.3) calls an LLM.

### 15.1 Page sections
1. **Summary card.** A deterministic template, never sent to an LLM. Inputs: θ per domain,
   THINKS_IN domains, and this week's band changes. θ (rounded to one decimal, as the page shows it) maps to words: θ ≥ 1 "advanced",
   0 ≤ θ < 1 "comfortable", −1 ≤ θ < 0 "building", θ < −1 "new to". Example:
   "Comfortable in finance, building in economics. You think in software. 6 concepts moved up a
   band this week." Only domains whose level was set or moved are named (decision 69 A2, `profile.rated_domains`:
   a comfort answer, θ ≠ 0, or level-setting evidence — a profile edit's level, a Quick check
   answer, "knew this" / opened explanations; home terms and other recorded ideas alone don't).
   Same inputs always give the same text (unit-tested).
2. **Domain cards** (Design pass). Per topic: a level word from θ (New to you, Getting there,
   Comfortable, Confident, Advanced) on a 5-step scale with its text, ideas known (edges at
   understands or above), interest in words, and "+N this week" from the week's band rises in
   that topic. Rated topics, topics with ideas known (an unrated one says "Not rated yet" with its
   count) and chosen topics first; the rest behind "Other topics" (decision 69 A2). As many across as
   fit (4 at 961px up to 7 at 1680px), rows filled evenly (`cardColumns`: six cards where five
   fit sit 3 + 3); 2 across to 960px, 1 to 420px.
3. **Knowledge map** (Design pass; replaces the Cytoscape/dagre map). An SVG overview of every
   topic first: "You" in the middle, one cluster per topic on a ring (deterministic layout with a
   fixed number of collision passes, `lib/mapLayout.ts`), solid dots for concepts **with recorded
   evidence** at heard of or above (filled by band, size by doc frequency, can explain ringed;
   decision 69 A: a prior guess is never drawn, no fallback domains, a domain with no nodes takes
   no slot, an empty map says so), outline rings for ready to learn (every prerequisite known by
   evidence at p ≥ 0.5, any domain), dashed rings for learning-goal targets, nodes that
   rose this week popping in once (not under reduced motion). Topic buttons (and clicking a
   cluster label) show one topic's subgraph (`?domain=`, ≤ 60 nodes) in the same layout; a goal
   shows its targets (`?goal=`). Keyboard: the SVG is one Tab stop with a label (roving tabindex;
   arrow keys move between nodes, Enter opens the inspector); each node's label says "label,
   band[, ready to learn][, in a goal]"; shapes carry the meaning as well as colour. The
   inspector beside the map shows the definition, "Why we think so" (the last 3 evidence items,
   "You know what it builds on" for a ring, "Nothing recorded yet" for a no-evidence node in a
   topic or goal view, which the legend names) and "I know this" / "I don't". Topic and goal views
   draw no-evidence nodes as `unaware` (hollow), never a prior band. **Levels (decision 69 A2):**
   a topic shows a level word (and joins the summary sentence) only when its level was set or
   moved (a comfort answer, the field, reading, answers, an edit); recorded ideas alone (home
   terms) don't rate it. The list view shows the
   same nodes by topic (the default below 640 px). **Size (Wide layout, decision 45):** beside
   the inspector (961px up) and in a box of 800px or more the map is laid out for the box
   (`mapSize`: its width in 40px steps up to 1160, height 680 to 780) and drawn at that pixel
   size, with the clusters on an ellipse so they reach the sides; stacked (960px and under) or
   in a narrower box (1024px) it keeps the fixed 760×600 canvas scaled in, and `layout()`
   returns exactly what it did before (pinned by a snapshot).
4. **This week.** Concepts that moved up a band in the last 7 days, and the
   annotations-per-1,000-words trend by week (falling = the overlay is learning). Since the Wide
   layout it sits beside Reading goals, above the map (on a phone: goals, this week, map).
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
- **Who (M7, Sourabh):** signed-in readers, and demo readers **for their own session only**: a demo
  edit changes that session's copy of the persona (`demo_graphs/{persona}`, incl. a session-only
  `thinks_in` frame used by explanations) and the session's settings, never the persona template;
  POST /v1/me/demo/reset returns it to the original. Caps: 10 parses/day per signed-in reader;
  3 per anonymous uid and 30/day shared across anonymous readers.
- **Parse.** One `MODEL_FAST` call, task `profile_edit`, prompt file
  `app/prompts/profile_edit.md` with a version header. The reader's text goes between content
  delimiters as untrusted data. The prompt gets only the text, the domain list and the allowed
  THINKS_IN list: no uid, no history, no concept ids. §11.3 redaction runs on the text first.
  The raw text is never logged or stored; logs carry `uid_hash`, op counts and cost.
- **Whitelist.** Vertex rejects tagged-union response schemas (and an outer `maxItems` next to
  inner ones), so the model fills a flat schema (`ModelEditOps`: op name plus every op's fields as
  plain enums/lists with empty defaults) and `strict()` re-validates each op against the strict
  Pydantic discriminated union with `extra="forbid"`: a field that doesn't belong to its op rejects
  the whole edit. At most 20 ops, at most 30 concept names per op and **30 distinct names per
  edit** (checked before linking); an id-shaped name (`c_…`) rejects the edit:
  | op | fields |
  |---|---|
  | set_domain_level | domain, level: new / some / comfortable / expert |
  | mark_concepts | names[], state: known / unknown |
  | set_thinks_in | domains[] (from the allowed list, ≤ 3) |
  | set_explanation_style | length: short / normal / detailed |
  | set_density | minimal / balanced / guided |
  | pause_learning | paused: bool |
  | set_interest (decision 48) | topic: the reader's own words for a subject, direction: more / less |
  The model fills `set_interest` as two flat ops, `read_more` / `read_less` with a `topic`
  (prompt `profile-edit-v7`): with a separate `direction` field it left the direction empty
  (evals: v6 9/10; defaulting an empty direction to "more" once turned "less cricket" into more,
  so that default was dropped; v7 10/10 twice, attacks 5/5). At most 3 distinct topics per edit,
  checked before any embedding (422 `too_many_topics`); an id-shaped topic rejects the edit.
  Any output that fails validation is rejected as a whole ("Couldn't understand that, try
  rephrasing"); nothing is partially applied.
- **Resolve.** Concept names go through the existing graph linker (§2: exact alias, then
  embedding candidates + at most 3 `link_confirm` batches); the model never supplies ids. Names that don't
  resolve are listed as "Couldn't find: …" and dropped from the edit.
- **Preview.** POST /v1/me/profile/edits parses and resolves, writes nothing to the reader
  model, and returns `{edit_id, preview}` (`preview.unresolved` lists names it couldn't find:
  returned only, never stored or logged; the edit doc keeps ops, values and resolved ids only). The preview is a diff: per domain θ
  before → after, concepts affected per direction with counts (expandable list), settings
  before → after. The pending edit expires after 1 hour. Nothing changes until the reader
  clicks **Apply** (POST /v1/me/profile/edits/{id}/apply).
- **Apply.**
  - mark_concepts: evidence weight **3.0** per concept (+ for known, − for unknown).
  - set_domain_level: target θ per level (new −1.5, some −0.5, comfortable 0.5, expert 1.5);
    θ ← θ + 0.5·(target − θ); then weight **2.0** evidence on the domain's core concepts (its 10
    highest-`doc_freq` concepts): + where b ≤ target, − where b > target.
  - style, density, THINKS_IN, pause: set directly on `users/{uid}`.
  - set_interest (decision 48): each topic phrase goes alone through the shared topic matcher
    (`app/me/topic_match.py`: whole-phrase alias → words and 2-word chunks → nearest topic by
    embedding); unmatched phrases are listed as "Couldn't find". `more` sets the domain's
    interest to max(current, 1.0), `less` to min(current, 0.3); the edit records `{domain:
    [previous, applied]}` and Undo restores the previous value only where the interest still
    equals what the edit applied (a later pick, Redo setup or edit wins). Preview line: "More
    Politics in your feed". A request that changes nothing ("less" on a topic already out of
    the feed) is dropped from the edit and the preview. Demo sessions drop it with the note
    "Feed topics are fixed in the demo". The phrase is never stored. Known limit: the guard
    compares values, so if a later change lands on exactly the value the edit applied (e.g. a
    Redo setup that also leaves a topic at 0.3), Undo restores the earlier value.
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

## 16. Up next and explore (recommendations)
End-of-article suggestions in this reader's frame: what to read, watch or listen to next,
mixing our own corpus with the web. Built in M6.5 with demo personas standing in for readers
(the reader graph replaces them in M4, exactly as for the placeholder scorer).

### 16.1 Triggers
The concepts this reader was shown as new in the article (the span annotations at balanced
density, highest score first). Every recommendation names the concept that triggered it.

**Card chips (decision 67 N, `basis=article`).** The note card's "Up next" row asks for
`basis=article`: the triggers are the article's own key ideas (`feed_rank.key_ideas`, its 4 most
salient linked concepts, the same for everyone), relevance by salience order, and the selection
keeps at most one item per format in the order read, watch, listen (`rank.one_per_format`); `why`
says "On ‘X’, a key idea here". An article with no linked ideas gets no chips. The chips sit at
the end of the card's scrolling body (never the pinned footer), one row that scrolls sideways
when narrow; a click opens like Up next (library in the reader, `open_here` web items brought in,
else the source in a new tab) and `rec_shown` is sent once per chip per page. The chips are asked once the page's notes have loaded (decision 68: a just-opened link is still being analysed before that, and the API answers 409). Chips that arrive after a card opened appear in it at once (`refreshNextUp`).

### 16.2 Library candidates (`app/recs/library.py`, pure, no API calls)
| relation | label | rule |
|---|---|---|
| same_story | Same story elsewhere | Syndicated text (5-gram shingle Jaccard ≥ 0.5), or the same event from another source: headline-word Jaccard ≥ 0.3, linked-concept Jaccard ≥ 0.2, published within 4 days |
| primer | Simpler primer | For each trigger, its prerequisites with prior < 0.6 for this reader (else the trigger itself); docs that explain that concept in their own text. A Wikipedia article whose title is the concept scores 1.0, other Wikipedia pages 0.8 × salience, explaining news 0.7 × salience |
| deeper | Go deeper | Concepts that list a trigger as a prerequisite; docs where that concept has salience ≥ 0.6 |
| angle | Different angle | ≥ 40% of the article's 5 most salient concepts, from another source; × 1.15 if from another country |
Wikipedia pages are evergreen (no freshness decay) and never count as same_story or angle.

### 16.3 Web candidates (`app/recs/web_search.py`)
- Providers behind one interface: **Tavily** for articles and for podcast episodes
  (`include_domains` = podcast directories), **YouTube Data API v3** for videos (search, then
  videos.list for durations). Keys are server-side secrets, never sent to the client.
- **Query = concept label + its graph domain + a format suffix** ("Repo rate policy explained",
  "… podcast episode"). The domain disambiguates labels; nothing about the reader (uid, persona,
  history, the current article) is ever part of a query (tested). Article-basis lookups (the card
  chips) use the same query shape on the article's key ideas (tested). **One exception (decision 69
  B2, Sourabh's answer "Go with what u feel is correct"; B4, "i want more on this story thing"):**
  the end-of-article story search sends the title, cleaned, ≤ 120 chars, of a **library (corpus)
  article**, or of a page a reader brought in that **this reader was shown as a suggestion** (its
  "web:" / "feed:" id, a hash of the result's own link, is in their served items: Up next, chips,
  For you, screen 2 — the link came from Gloss's own suggestions, search results or the outlet
  lists, not from the reader); only articles (not videos or podcasts) brought in through
  Open here / Open any link (`user_ingested`), never extension text. A link this reader was never
  shown never matches (pasting a link they were shown does); a link normalisation changed doesn't
  match either, so the rule fails towards privacy (tested). A library article's story results are
  shared by every reader; a brought-in page's are shown only to readers served its link (other
  readers, and other demo personas, see its key ideas only). Served ids age out past the newest
  300, and with them the page's story items. A brought-in page may start a search only while the
  day's story calls are under half the cap (library articles keep the rest) and only with a real
  title (not the site name or link extraction falls back to). Results are stored per page, keyed
  `story:{content_id}` per format (article via Tavily news, video via YouTube), searched once ever
  (stored even when empty), its own `STORY_SEARCH_DAILY_CAP` (40) within the global, YouTube and
  anonymous caps, never the feed's. Results must not be the article itself (by URL hash) and must
  name one of its top 3 key ideas or share ≥ 2 distinctive title words; up to 2 lead the end list
  as "More on this story", included even when the ranking would leave them out (`basis=story`;
  the card chips stay `basis=article`). The rest of that list spreads over the article's ideas
  (decision 69 B3): each idea's n-th item counts 0.5^n before ranking, and at most 2 items follow
  any one idea.
- Every result is normalized to `{url, title, source, format: article|video|podcast,
  duration_or_read_time (s), snippet, thumbnail, published_at}`, filtered by the domain
  blocklist (`app/recs/blocklist.txt`, subdomains included) and a relevance gate (the title or
  snippet must name the concept), then cached in Firestore `rec_cache/{concept_id}__{format}`
  for 48 h, keyed on a versioned query so a changed query refetches.
- Up to 3 triggers × 3 formats per article. Misses are fetched in the background; the first
  response may hold library items only, with `pending: true`, and the client polls briefly.
- **Daily cap** `SEARCH_DAILY_CAP` (300 calls, all providers) plus `YOUTUBE_SEARCH_DAILY_CAP`
  (90 searches; each costs 2 calls). Calls are reserved under a lock before they are made. Past
  a cap, no call is made and cached (even stale) results are served, as with the LLM budget.

### 16.4 Ranking (`app/recs/rank.py`, pure)
```
score = relevance × relation_weight × format_affinity × freshness × not_seen
```
- relation_weight: primer 1.0, explainer (web) 0.95, deeper 0.9, angle 0.85, same_story 0.8;
  × 0.6 per dismissal of that relation by this reader, floored at 0.3.
- Decision 68: a signed-in reader who answered read / watch / listen gets the prior "chosen 0.75,
  others 0.4" (`rank.prior_for`) in Up next, the card chips (chosen formats first) and the feed;
  demo personas keep theirs.
- format_affinity = 0.5 + α/(α+β): Beta prior of strength 4 at the reader's default mean per
  format, α += clicks + 2 × completions, β += dismissals + 0.1 × shown-without-click. An
  explicit Read / Watch / Listen choice sets that format's mean to 0.9 and scales the others by
  0.6. Articles get × 1.2 when their length matches the reader's preference (short ≤ 5 min,
  long ≥ 8 min) and × 0.85 when it opposes it. Demo defaults: newcomer prefers video, trader
  short articles, policy_student long reads.
- freshness = 0.6 + 0.4 × 0.5^(age_days / 30); undated or evergreen 0.85.
- not_seen: 0 if completed or dismissed, 0.3 if clicked, 0.8 if shown 3+ times, else 1.

### 16.5 Selection
- 6 items. The reader's preferred format (explicit choice, else highest affinity) gets 3 slots,
  the next two formats 2 and 1 by affinity. A format with too few qualifying results passes its
  spare slots to the next format in order.
- When both kinds qualify, at least one library item and one web item: a missing kind replaces
  the weakest pick of its own format. Final order is by score.
- Each item: relation label, format, title, source, length, a "why this" line from a template
  that names the triggering concept ("Because ‘yield curve’ was new to you"), the trigger ids,
  and "From the web" for web items.

### 16.6 Opening items and signals
- Library items open in the ReadLayer reader. Web articles offer **Open here** (POST
  /v1/recs/open: safe_fetch and the normal ingestion pipeline, `source: user_ingested`, within
  the per-user daily cap) and **Open original**. Videos within the cap and Apple episode links
  carry `open_here` and open in Gloss (§21); other recordings open the original in a new tab. "Open here" moves to two-phase loading (article first, annotations after) in the rest of
  M6.
- Events `rec_shown`, `rec_clicked`, `rec_dismissed`, `rec_completed` (a recommended library
  article read to the end) update format stats, relation dismissals and seen items.
- Storage (M3): `users/{uid}/rec_signals/{persona|default}` and `users/{uid}/ingest_counts/{day}`
  (§4), covered by export and delete. Personas apply to anonymous demo readers only; signed-in
  readers use `default` and a neutral format prior until onboarding (M7).

## 17. For you feed (M7.5, decision 33)
A daily page of articles, videos and podcasts on the reader's topics, ranked for what this reader
is ready to learn. No LLM anywhere on this path.

### 17.1 Topics and searches (`app/recs/feed.py`)
- **Topics.** Up to 6 taxonomy domains the signed-in reader chose or raised (interest ≥ 0.5;
  onboarding stores 1.0 for chosen domains and 0.3 for the rest), strongest first, ties in
  taxonomy order; if none is that strong, their strongest stored domains; none stored → the
  four business domains. Demo personas have a fixed pair: newcomer
  technology + economics, trader finance + business, policy student policy + politics.
- **Query = the taxonomy label + a fixed phrase**, nothing else: "Health news this week" (Tavily,
  `topic: news`, last 7 days, 10 results for one credit), "Health podcast" (Tavily, podcast directories), "Health
  news explained" (YouTube, 4–20 minutes, published in the last 30 days). Never reader text,
  ids, history or the current article (property test over all 14 domains). A changed phrase
  makes that day's cache entry stale.
- **Shared and day-keyed.** Each (topic, format, UTC day) is searched once for everyone and
  cached in `rec_cache` under `feed:<domain>:<day>`. Results pass the blocklist, a page-shape
  check (an article URL must not be a section, tag or home page: a ≥ 3-word slug or a date/id
  in the path; podcast chart and genre pages are dropped), the 14-day article filter (when a
  date is given), an English-only check (at most one title letter outside Latin script, decision
  64; YouTube's language setting is only a hint, and a video whose `defaultAudioLanguage`, else
  `defaultLanguage`, is declared and not English is dropped by the provider) and a relevance
  gate: the title or snippet names the topic (its label, the first 4 letters of a long label such
  as "tech", or a word of the domain's taxonomy scope line such as "AI" or "inflation"), or a graph
  concept of that domain as §17.2 names them (sports news rarely says "sport", but it names a
  penalty kick; a single word counts only as the concept's own label or a caps acronym).
- **Caps.** `FEED_SEARCH_DAILY_CAP` (60 calls/day) is reserved under the same lock as the global
  and YouTube caps; past any of them nothing is called and cached results are served.
- **In-request only.** Missing searches run inside the request with a 6 s limit (Cloud Run
  throttles CPU after a response). What doesn't finish is `pending: true`; the client asks again
  and joins the same in-flight task, so a re-ask never searches twice. Provider results vary
  from run to run, so a day entry that came back empty may be searched again after an hour.
  Bound: each API instance makes at most 2 searches per (topic, format, day), so at most 6 with
  ≤ 3 instances, all inside `FEED_SEARCH_DAILY_CAP`. Onboarding (§4) uses the same searches:
  ≤ 18 topic searches and ≤ 2 concept searches per onboarding; concept searches also count
  against a shared `ONBOARDING_CONCEPT_SEARCH_DAILY_CAP` of 20 (ops/search `onboarding_concept`),
  and a reader's discover calls that start new searches against 3 a day (re-asks that join
  in-flight or cached searches are free).
- **When a search can't run** (a cap, a provider failure, or that bound) and today has no
  entry, yesterday's entry for the same topic and format is served if there is one; after a
  cap hit or failure that instance waits 10 minutes before trying again.

### 17.1a Articles from top outlets (decision 50)
Search results were too often small local papers or tag pages, so **articles now come from top
outlets' own section feeds**; the search above is only a restricted fallback.
- **Registry** (`app/recs/outlets.py`): global = BBC, The Guardian, NPR; India = The Hindu, Mint.
  Each maps the 14 topics to section feeds (closest section where it has none). Every outlet was
  measured readable through our own fetch + extract (≥ 2 of its 3 newest articles ≥ 400 words,
  rule fixed beforehand; `scripts/check_outlets.py`, `docs/evidence/d50/outlets.txt`); The
  Indian Express and The Economic Times failed it and are out.
- **Collection job** (`app/recs/outlet_job.py`): Cloud Scheduler calls
  `POST /v1/internal/feeds/collect` at 06:00 and 18:00 IST. Every feed is fetched once through
  `safe_fetch` (feed content types, 3 MiB cap, robots.txt) and parsed from those bytes
  (`feedparser` never gets a URL). Kept: the outlet's own article hosts, https, no live/video/
  audio/hub path, dated within 3 days, a Latin-script title (§17.1), and a section that fits the
  topic: `stage`, `film`, `music`, `books`, `travel` and the like only for culture, `sport` only
  for sports (decision 64: the Guardian's world feed carried a theatre piece into politics); URLs
  canonicalised (tracking query and fragment dropped). Section and script are checked again when
  stored lists are read (`fits_topic`), since a list keeps earlier items for days.
  One doc per topic, `rec_cache/outlets:<topic>` = `{outlet: {items ≤ 20
  newest, fetched_at}}`, merged per outlet: an outlet that failed keeps its list, and the 3-day
  filter is re-applied to every list each run. 14 writes a run; no reader data, no LLM, no search
  API. A newest run older than 36 h is logged by the feed.
- **Country and the mix.** A reader's `country` (IN, GB, US, other; §11.4) decides sides: their
  own country's outlets are *local*, the other global outlets *global*; another country's
  national press isn't offered. No country (or "other") → global outlets only. Over all article
  picks the local share is round(0.6 × slots) when supply allows; a short side is backfilled
  from the other (`feed_rank.article_split`). Videos and podcasts are outside the mix. Demo
  personas read as India (`PERSONA_COUNTRY`, decision 51).
- **Fallback.** A topic with fewer than 3 offered outlet articles, and every onboarding concept
  search, makes one article search with Tavily `include_domains` = every registry article host
  plus reuters.com and apnews.com, one constant list for everyone (never `exclude_domains`), under
  new keys `feedx:<topic>:<day>` / `feedx:c:<concept>:<day>`, so the old unrestricted `feed:`
  article entries are never served again. Results from outlets the reader isn't offered are
  dropped after the search; requests never differ by country (test).
- **Refresh.** For you refetches on `rl:feed-stale` (Redo setup finished, a profile edit applied
  or undone, a learning goal saved or removed, a country change) and on its Refresh button;
  outlet articles cost no search.

### 17.2 Ranking (`app/recs/feed_rank.py`, pure)
```
score = interest(topic) × format_affinity(format) × readiness × goal_boost × freshness
```
- interest: stored domain interest, normalised so the top topic is 1.0.
- format_affinity and freshness: as Up next (§16.4), sharing its per-reader format model.
- Per-topic quotas (decision 68, `quotas_for`, signed-in live feed only): a chosen format 3
  (podcast 2), an unchosen one 1 (articles 2); all three or none → 3 articles, 2 videos, 1 podcast.
- readiness: concepts the item names (`named_concepts`: exact label/alias match over 1–4-word
  n-grams of title and snippet, longest first) that are new to this reader (p_know < 0.5): 1–4
  new → 1.0, none → 0.6, more than 4 → 0.8^(k−4). A **single word** names a concept only when
  unambiguous (decision 64): a caps-only name (RBI, M&A, EBITDAR) needs the word in caps, in any
  domain; otherwise only the plain label counts (no alias: "stocks" ≠ Stock variable; no
  disambiguated label: "basis" ≠ Basis (finance)), and only in the item's own domain or a related
  one (`DOMAIN_GROUPS`: the business group, and policy with politics, decision 65). The alias index never holds a one-word stopword alias ("to", "it",
  "AT": §2's lookup, `ALIAS_STOPWORDS`).
- goal_boost: 1.3 when the item names a learning-goal target (§18).
- Selection: per topic up to 3 articles (mixed local/global, §17.1a), 2 videos, 1 podcast (one
  per URL; a URL under two topics belongs to the earlier), then the topics' picks interleaved by
  score, at most 24. Each item carries a `why` line ("Health · 2 ideas new
  to you · helps your goal: Insulin resistance").
- Feed impressions use the Up next signal store with relation `feed`; feed dismissals never
  touch relation dismissals.
- Readiness line (decision 60, For you only): from the reader's own map, one line under the
  title. Its ideas (decision 65): for a public library article (a stored corpus doc whose id is
  `url_hash` of the row's URL; a reader's own `user_ingested` or extension page never counts) the
  article's **key ideas**, its K = READY_MAX = 4 most salient linked demands in the served graph,
  one per concept; for every other row the named concepts above. A prerequisite the article
  itself links is never "read up on" it. The line, its read-first ideas and the `why` count use
  these ideas; the score (its readiness factor and the goal boost) always uses the title and
  snippet concepts, so the row order never depends on it. "Mostly familiar": none is new; "Ready for you": 1–4 new and every
  new idea's graph prerequisites are known (the map's rule, p_know ≥ 0.5); "A stretch: read up on X
  and Y first": a new idea has a prerequisite that is itself new and not named by the item (up to
  2, most basic first by `base_difficulty`), or "A stretch: many new ideas at once" for more than 4
  new. An item that names no concept gets no line. A new idea with no prerequisites in the graph
  counts as ready here but gets no ring on the map. The line says its basis on hover
  (`readiness_basis`: "Based on the main ideas in the article" or "Based on the ideas named in the
  title and summary"); it is three levels, not a number, because a number from four ideas or a
  title match would be false precision. Scores are unchanged.

### 17.3 Demo snapshots (decision 38)
Demo readers never trigger a search. `scripts/seed_demo_feed.py` reads the collected outlet
entries as an Indian reader (local, global, local pattern), runs the video and podcast searches
once and stores `persona_feeds/{persona}` (public items only), dropping any article that fails a
local fetch-and-extract check (≥ 400 words). Serving applies no date filter, and the page says
the picks were prepared in advance, may be dated, and that signing in with Google gives a live
feed.

### 17.4 Opening items and pasted links
Feed articles open through "Open here" (POST /v1/recs/open, two-phase, §3). The library's **Read
any link** box uses the same route. So do videos and podcast episodes (§21), stored as `user_ingested`. Pages that reach ReadLayer this way (`user_ingested`) or from
the extension (`extension`), the `NOT_CORPUS` sources, are private to the readers who brought
them in: `users/{uid}/ingested/{content_id}` is written on every successful open, and the library
list and Up next drop other readers' `NOT_CORPUS` docs per request, after the shared caches (Up
next filters before its per-relation cut). A `user_ingested` doc (fetched by the server itself)
stays reachable by id; POST /v1/content with a URL stays public (source `fetch`). An `extension`
doc is readable **only** by readers whose `ingested` holds it (M8, decision 52): content, annotations,
explain, recommendations, analyse and saved answer anyone else with the same 404 as an unknown
id, since its text can be a subscriber's paywalled article and its id derives from the URL.

## 18. Reading goals (M7.5)
Signed-in readers only, after consent, at most 5, stored at `users/{uid}/goals/{goal_id}`.

- **Habit:** `{metric: articles | minutes, per_week}` (1–50 articles or 10–600 minutes).
  Progress is this ISO week's (UTC) `weekly` doc: articles = `content_ids` (written when
  annotations load), minutes = `words_read / 230`. While learning is paused nothing is recorded,
  so the goal says "Learning is paused, so reading isn't counting" instead of silently showing zero.
- **Learning:** "understand X". The text is redacted (§11.3), a leading "understand / learn /
  get" is stripped, and X is resolved by `resolve_names` (exact label or alias, then embedding
  candidates + `link_confirm`), which sees only the redacted phrase. Targets = the concept plus
  its prerequisite chain, most basic first, at most 8. **Only the target ids and labels are
  stored; the text is never stored or logged** (logs: `uid_hash`, outcome, cost). Unresolvable
  → 422, nothing stored. `GOAL_RESOLVE_DAILY_CAP` 10 per reader per day.
- **Topic goals (decision 48).** Order for X, one phrase, embedded at most once: exact concept →
  whole-phrase topic alias (no model call) → `resolve_names` → words and 2-word chunks →
  nearest topic by embedding. A topic match is a goal on the topic (label "Politics", `kind:
  topic`) whose targets are up to 10 concepts of that domain sharing a whole word with X (the
  topic's own label word doesn't count; plurals folded), most read first, then the domain's most
  read concepts (doc_freq 0 only if short). **Preview, then save:** POST /v1/me/goals/preview
  resolves (charged to the cap) and writes nothing; POST /v1/me/goals `{type:
  learning_resolved, kind, concept_id | topic, target_ids}` saves the previewed ids after
  re-checking them against the graph (no model call, no cap). The preview line shows the
  reader's words from the page only ("Goal: understand Politics (Indian politics) · 10 ideas");
  the stored goal never has them.
- **Known** = band "understands" or "can explain", i.e. current p_know ≥ 0.5 from `knows` with
  forgetting, else the IRT prior. Learning progress = known targets / targets. Pure math in
  `app/reader/goals.py`, no LLM.
- **Where it shows:** the profile's Goals section (progress bars with text values), the feed's
  goal boost and `why` line (§17.2), and the knowledge map, which rings goal targets and offers
  a "Goal: X" view (GET /v1/me/graph?goal=).

## 19. Gloss UI (Design pass, decisions 39 and 40)
The product is called **Gloss** in the UI, README and deck; the repository, Firebase project,
URLs, ids, storage keys and API names keep "readlayer". Visual target: `docs/design/mockup.html`.
**Wording (decision 67):** the UI calls the person a **consumer** (they read, watch and listen) and
never names the mascot ("Tell Gloss about you"); this document keeps "reader" as the internal
term, as do code, API fields and prompts. Guarded by `apps/web/test/wording.test.ts` and
`apps/api/tests/test_wording.py`.

- **Tokens and type.** White paper / #121212 in dark, near-black ink, one teal accent that only
  means "a note for you", `--accent-line` for strokes that must read (≥ 3:1 on paper in both
  themes), `--mark-goal` for goal dashes. Schibsted Grotesk for UI and headlines, Source Serif 4
  for reading (article body 21px, 19px under 600px), metric-matched local fallbacks
  (`tools/shots/font_metrics.py`). No reader-facing text under 13px; controls ≥ 44px.
- **Margo** (`components/Margo.tsx`): one ink outline and one teal swipe; moods idle, think,
  happy, oops and a 16px mark (favicon, extension icon `public/margo-mark-128.png`). Appears in
  the logo, the reader's margin header (idle; an occasional blink only before the reader scrolls
  into the article, never while they read or a note is open, none under reduced motion), the notes-loading notice (think), the recap (happy) and empty and error
  states (oops). Never in article text, never on note cards. Always `aria-hidden`.
- **Wording (decisions 67, 69 F)**: the UI says "consumer", never "reader"; where "read" meant what
  the consumer does in general it says "consume" or a format-neutral word ("Open any link", "Where
  are you based?", "Start exploring", "Your profile"). Article format words ("I'd read this", "min
  read", "Before you read"), Gloss reading a page, the "read up on" readiness idiom and the
  `consent-v2` text keep "read". `test/wording.test.ts` guards it (a kept line says `wording-ok`).
- **Top bar**: logo, search, "Open any link" (focuses the sidebar field, else a dialog), the demo
  persona chip, theme, account.
- **Library**: tabs For you (the feed, §17) · Topics (the corpus with topic and source filters) ·
  Saved; single-column rows (source initial and name, "in Topic · format", bold title, serif
  subtitle, time, "N ideas new to you", save where the row has a library id, "show less" on feed
  rows) and a sidebar with Open any link, goals and topic chips. **Wide layout (decision 45):**
  the top bar, library and profile share one container, 1280px and 1520px from 1440px; rows up
  to 820px wide with a 4:3 thumbnail from 1280px. The sidebar has two groups, tools (Read any
  link, Topics for you) and the reader's own (Your map this week, Your goals): one column up to
  1439px, side by side from 1440px (the third column), DOM order equal to visual order. **Your
  map this week** (from 961px, where the sidebar is beside the feed; a lazy chunk; two reads, asked for
  after the library's first answer: `GET /v1/me/graph?view=overview` for the dots and
  `GET /v1/me/profile` for the week): a tile per topic with a small cluster of dots (up to 8 a
  topic, 24 in all: this week's risers first and haloed, then known ideas, with up to 2 outline
  rings kept for what is ready to learn next), the topic's name in text with "+N this week" when
  ideas rose, the week in one line ("3 ideas moved up this week: …"), a key and a link to the
  full map. **Every number comes from the profile's `week.moved_up`**, the same uncapped list
  its "This week" shows; the overview keeps only a topic's top 12 ideas (by band, then
  frequency), so a rise from unaware to heard of is usually not among its nodes and nothing is
  counted from them. No per-topic total of ideas is shown, for the same reason. If either read
  fails the panel says the map didn't load rather than claim a quiet week. The overview carries
  at most six topics, so a rise in a seventh is named in the line but has no tile: the tiles'
  "+N" can add up to less than the line, on purpose. It is a picture with a text equivalent, not a
  control, and not a scaled copy of the profile's map (STATUS §4). From 1440px both groups stay
  beside the feed while it scrolls (a group taller than the window scrolls inside itself). The
  week panel and the reader's spine sit in a boundary, so a chunk that fails to load leaves the
  page standing.
- **Reader**: kicker, 44px title, serif dek, byline; a sticky action bar (notes density Fewer /
  For me / More, Helpful, save, copy link, open original) and a reading-progress line; "Before you
  read" as a path (the known prerequisite where it starts, ticked; the article's key idea last; a
  step shows its definition or links to an explainer); the margin lists "N notes for you" with
  Margo until a note opens there as a sidenote; **"What this article changed"** at the end: the
  bands that moved since the notes loaded (`POST /v1/me/bands` at load and at the end, after
  flushing events), each with Undo (the opposite correction, so the row then shows the resulting
  band), the "Not really" answers as one row each ("Next on your path", never also a band move),
  and up to two Up next items that teach them, else Up next's top two under a neutral "Read
  next"; then Up next. **Wide layout (decision 45):** from 1280px a slim left rail, the
  **reading spine** (a lazy chunk): the notes count, minutes left ("Finished" at the end) and a
  track of the whole article with a dot where each note sits (solid new, ring refresher, the
  hovered or open note's dot enlarged) and the part above mid-screen filled. Articles are stored
  without headings, so this stands in for "contents" (STATUS §4); the dots are a picture, the
  margin list and the highlights are the controls. The text column stays 680px; the grid is
  1164px at 1280 and 1392px at 1920; the right margin is 300–360px.
- **Profile**: the Gloss title, the summary as a serif lede, domain cards, the map (§15.1).
  **Wide layout (decision 45):** the library's container; topic cards 4 to 7 across with rows
  filled evenly; the map laid out at its box's own size; the sections around the map in pairs
  (Reading goals | This week, Analogies | Preferences, Describe yourself | Your data), side by
  side from about 1000px.

## 20. Landing (Landing and onboarding, decisions 41, 44, 45)

### 20.1 Problem illustrations (decision 44 V3)
- **Model:** `gemini-3.1-flash-image` on Vertex (`MODEL_IMAGE=vertex_ai/gemini-3.1-flash-image`,
  location global), through `llm.generate_image`, task `landing_art`, one attempt per call.
- **Prompt:** `app/prompts/landing_art.md`, version `landing-art-v1`, with the Margo favicon
  rasterised to 512px as the character reference. Scenes (in `scripts/landing_art.py`): *jargon*
  (Margo frowning at dense text, three words underlined in teal, a question mark), *tabs* (a
  dozen tabs bursting out of a laptop, Margo overwhelmed), *shredder* (a full page in, a
  three-line strip out, Margo worried). No article text and no reader data in any prompt.
- **Run (2026-10-11):** 5 images generated, $0.339 (5 × $0.0679), within Sourabh's six-image,
  $0.60 approval. Vertex returned 429 on two calls (not billed: the ledger rose by exactly the
  images made); the sixth was not retried because every scene already had a usable pick.
- **Picks:** jargon v1 (v2 drew Margo as a human girl, off-model), tabs v2 (Margo present, clearer
  tabs, more teal), shredder v1. Candidates: `docs/evidence/landing/illustrations/`.
- **Processing:** white un-premultiplied to transparency (anti-aliasing kept), trimmed and padded
  to 5:4, WebP (cwebp q82) at 460 × 368 and 920 × 736 in `apps/web/public/landing/problem-*.webp`
  (21–45 KB at 1x). `<img>` with alt text, lazy, explicit size (`landing/ProblemArt.tsx`).
- **Dark theme:** `filter: invert(1) hue-rotate(180deg)`. Teal strokes measured on the band:
  6.3:1 on the light wash, 8.0:1 on the dark wash (≥ 3:1 for graphics).
- Footer credit: "Illustrations made with Google's image model."

### 20.2 Landing refresh (decision 61, plan `docs/plans/landing-refresh.md`)
- **Formats, honest:** every format gets notes (articles, any link, YouTube videos up to 10
  minutes, Apple Podcasts episodes up to 12, news pages in Chrome through the extension); longer
  recordings open where they play. One full list in `landing/formatsFull.ts` (landing chunk) with
  the caps as constants that a vitest checks against `apps/api/deploy.env.yaml` and
  `app/config.py`, and with `MEDIA_VIDEO_ENABLED` true; the hero's chips (`landing/formats.ts`,
  main bundle: "Articles", "Any link", "Short videos", "Podcasts", "Chrome extension") are a
  projection of it, also tested. The "others in your feed" legend is gone.
- **Sections after See it in action** (landing chunk, paper / wash bands kept alternating):
  *Gloss in your browser* (wash band): a laptop still of the production extension 0.8.1 on
  Wikipedia's Yield curve article with a note open and the popup over its top right; the README's
  access words (no access until clicked; never mail, banking, sign-in or private pages, or a page
  with a password or card field; emails, phone, card, Aadhaar and PAN numbers removed on the
  device); the README's four install steps; a link to the pinned release
  `releases/tag/extension-v0.8.2` (0.8.1 until decision 62; the still stays the 0.8.1 popup, which looks the same on an article). No Web Store or other-browser claim. *Watch and listen*
  (paper): the caps, Open any link, time buttons, the reader's own caveat that the transcript is
  made automatically; a laptop still of the Fireship video with the Decompiler note open.
- **See it in action:** the feed still re-recorded with readiness lines ("Ready for you", "A
  stretch: read up on Income distribution first") and "Open in Gloss". **How it works** step 4
  adds that For you tells you which picks you're ready for. **Footer:** "Get the extension".
- **Stills:** AVIF + WebP at 1x and 2x through `Still` (lazy, explicit size), ≤ 120 KB at 1x and
  ≤ 250 KB at 2x; a text-heavy page falls back to near-lossless WebP (`tools/shots/stills.py`).
  Captured on production by `tools/shots/landing_media.py` and `landing_extension.py` after the
  read-only `landing_media_precheck --refresh`.


## 21. Media: videos and podcasts (decision 54, plan `docs/plans/media.md`)

A YouTube video or an Apple Podcasts episode opens in Gloss like an article: the recording plays
at the top of the page, its transcript is the text, and the transcript goes through the same
phase 2 (§3) and the same notes. The recording is never changed; the transcript is labelled as
made automatically, and the player is the source.

### 21.1 Scope and caps
- **Links:** YouTube watch, `youtu.be`, shorts and embed links; Apple Podcasts **episode** links
  (`?i=`). A show page answers `not_an_episode`, a direct `.mp3` link `apple_link_only`,
  Spotify and M4A episodes "Open original". English only.
- **Length:** videos 10 minutes (`MEDIA_MAX_VIDEO_S` 600; Sourabh, 2026-10-14: "small 10
  minutes clips are good enough"), podcasts 12 (`MEDIA_MAX_AUDIO_S` 720, Sourabh the same day:
  Apple's length leaves out stitched-in ads; an episode listed at 9:25 downloaded at 10:52),
  `MEDIA_MAX_AUDIO_BYTES` 24 MB. A video is always one call; an episode is one call up to 11
  minutes (a tail under a minute joins window 1) and two sequential calls from 11 to 12. The code
  handles longer recordings (several audio windows, two in parallel) if the caps are raised.
- **Switches:** `MEDIA_ENABLED` (all media), `MEDIA_AUDIO_ENABLED`, `MEDIA_VIDEO_ENABLED`. A
  switched-off kind answers `media_off` before any I/O and is never remembered as a refusal, so
  turning it back on works at once. A transcript already stored stays readable. The web's copy
  follows a build-time flag, `VITE_MEDIA_VIDEO`, which `make deploy-web` reads from the API's
  `deploy.env.yaml`, so the two can't drift.
- **Caps (§11.5):** new recordings per signed-in reader per UTC day `MEDIA_DAILY_CAP` 5, per
  demo reader 1, all demo readers together 10 (`users/{uid}/media_counts/{day}`,
  `ops/media/days/{day}`); lookups (videos.list, Apple lookup, audio head) 300 a day for
  everyone (`ops/search/days/{day}.media_lookup`, never the search caps); a separate media
  budget `MEDIA_DAILY_BUDGET_USD` $3 inside the $8 guard (`media_usd` on the spend doc).

### 21.2 Open (`app/media/service.open_media`, inside POST /v1/recs/open)
1. `urls.classify` → `YouTube | ApplePodcast | AudioFile | None` (None = an article). The
   canonical URL's hash is the content id, so every spelling shares one transcript.
2. Stored `contents/` doc with `media` → ready, free. A refusal remembered today
   (`ops/media/days/{day}.refused`) → the same 422, free. A live pending doc → its stage, free.
3. Otherwise: reader slot → lookup → media budget pre-check (duration × `MEDIA_EST_USD_PER_MIN`)
   → growth slots → `pending_contents/{id}` with `stage: "transcribe"`, the `media` block, no
   paragraphs, `source: user_ingested`. A refusal refunds the slot and is remembered for the day.
- **YouTube lookup:** `videos.list` (1 quota unit): public, embeddable, not age-restricted, not
  live, 30 s to the cap, English by `defaultAudioLanguage` when set and a Latin-script title
  (at most one letter outside Latin script, §17.1).
- **Apple lookup:** `itunes.apple.com/lookup` with our own digits (latest 200 episodes), the
  episode's `episodeUrl`, MP3 only, length within the cap; then `audio_head`, a 64 KB ranged GET
  through safe_fetch (§11.2): `audio/mpeg`, a total size within the byte cap, an MP3 frame.
  Missing length → estimated from the first frame's bitrate.
- `scripts/ingest_media.py` (demo seeding) calls the same function with no reader: no daily
  slot, no growth slots; the lookup cap, budget and every check apply. `--dry-run` prints the
  checks and window plan and writes nothing.

### 21.3 Transcribe (POST /v1/content/{id}/transcribe)
- `llm.transcribe` (§10) on `MODEL_QUALITY`, low thinking, 90 s timeout, prompt
  `transcribe-v1`: verbatim, in the language spoken, paragraphs with `MM:SS` starts and the
  language. The model gets the recording and fixed text only; spoken instructions are data.
  `MODEL_FAST` dropped a third of the speech on a measured window, so it is not used.
- **YouTube: one call on the whole URL, no offsets** (fps 0.1, low detail). Vertex offset windows
  hung with no error on 5 of 5 tries (plan Round 4), and whole-URL calls on 16- and 19-minute
  videos timed out at 90 s; at ≤ 10 minutes the whole-URL call answered in 45–51 s (step 7
  probe, 2026-10-14), so videos ship on. A timed-out call is charged its estimate once and
  answers 504; the page retries once, then offers "Try again".
- **Audio:** `fetch_audio` through safe_fetch (6 redirects, 45 s, the byte cap mid-stream, audio
  types only; bytes held only for the request, never stored or logged), an MP3 frame walk, pieces
  cut on time only at frame boundaries (`mp3.split`, piece *i* = window *i*), each sent inline.
  The walk's length replaces the lookup's. One audio run per instance (`Semaphore(1)`, tried
  without waiting; busy → 202). A retry whose bytes differ (dynamic ads) drops saved windows.
- **Checks per window** (`transcript.check_window`, one re-ask, then the attempt fails): output
  cut off, times outside the window, a repeated paragraph, over 300 words a minute. Under 80 words
  in all → `no_speech`; not English → `not_english` (an unknown language runs window 1 alone).
- **Cost:** audio tokens priced from `MODEL_AUDIO_PRICE_OVERRIDES` ($2.50 per 1M, no billing
  check yet) or the call is refused; each window is saved as it finishes, a retry pays only for
  missing windows, and an item stops at 2× its estimate across all attempts (`too_costly`).
- Success → paragraphs with `start_s`, `stage: "analyse"`; phase 2 then runs unchanged and copies
  `media` and `start_s` into `contents/`. GET /v1/content shows `transcribing`, `analysing`,
  `ready`, `refused {code, message}` or `failed`.

### 21.4 Reading (`apps/web`, the lazy `MediaReader` chunk)
YouTube is click to load, on `www.youtube.com` (decision 55: the no-cookie player can't see a
signed-in viewer's YouTube session and was answered "Sign in to confirm you're not a bot"); audio
is `<audio preload="none">`. Each
paragraph has a time button that seeks and plays; the spoken paragraph is marked and followed
unless the reader scrolled in the last 5 s. Under the title: "A transcript made automatically from
the video. It can contain errors, and filler words are often left out; the recording is the
source." Cards say "What the speaker is saying". Feed and Up
next rows get `open_here` from the server (`openable`): a video or Apple episode **of known length**
within its cap (an unknown length stays "Open original": most episodes from search run past the
cap); for demo readers it turns off once the shared demo cap is used. A For you row for a recording
that opens here offers both **"Open in Gloss"** and the original ("Watch on YouTube", "Listen on
Apple Podcasts"); a long or unknown-length one stays original-only (decision 55). Up next names
the original the same way beside "Open here". The privacy page says what YouTube and podcast hosts
see (R10).

## 22. Web addresses and Open in Gloss (decision 62, plan `docs/plans/gloss-address.md`)
- **Two addresses, one build.** `https://glossreader.web.app` (the name readers see) and the
  earlier `https://readlayer-sourabh-26.web.app` are two Firebase Hosting sites in the same
  project (`firebase.json` targets `gloss` and `app`, identical config); `make deploy-web` deploys
  both. CORS allows both sites on both domains and the extension, nothing else (a test reads
  `.firebaserc` and `deploy.env.yaml`). Sign-in state is per address.
- **Fresh after a deploy (decision 69 E).** Pages, `/index.html` and `/theme-init.js` are served
  `Cache-Control: no-cache` (revalidated on every load); Vite's hashed `/assets/**` are
  `immutable` for a year; `/fonts/**` keep theirs. The SPA rewrite is `^/[^.]*$` (routes have no
  dot), so a missing old chunk is a 404, never `index.html`. Hosting regexes are RE2 (no
  lookaround); `test/hosting.test.ts` guards both.
- **Sign-in names Gloss.** On `glossreader.web.app` the Firebase `authDomain` is that host, so the
  popup runs through its own `/__/auth/handler` and Google's chooser names it (`lib/sites.ts`
  `authDomainFor`); every other host keeps the built `authDomain`.
- **Extension 0.8.2.** Web base `glossreader.web.app`; it accepts Connect from both sites. The
  session remembers the origin it was connected from (`webOrigin`, only if allowed), and the
  popup's links, the overlay's links and Open in Gloss use it, so the reader lands where they are
  signed in. 0.8.1 lists only the old address; the Connect page there says so and links 0.8.2.
- **Open in Gloss on YouTube.** On a YouTube video page (the links the API's `media/urls.py`
  accepts; one shared fixture tests both) the popup's main button is "Open in Gloss" instead of
  "Read this page". The worker re-reads the tab's URL, sends only
  `https://www.youtube.com/watch?v=<id>` to `POST /v1/recs/open` (as Open any link does), and opens
  `/read/<id>` (plus `?persona=` for a demo persona other than the default) in a new tab.
  Refusals show the API's words without its "Open original" sentence. Privacy: the video is a
  `user_ingested` doc like a pasted link (only `extension` docs are private), so anyone with its
  id can read it; only the reader's `ingested` entry is theirs. README and the privacy page say so. No new permission:
  `activeTab` gives the tab's URL once the reader clicks the toolbar button.
