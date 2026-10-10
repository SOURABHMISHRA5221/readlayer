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
  affected docs, without a rebuild.
- Wikidata ids: robots.txt disallows the Wikipedia/Wikidata APIs for our agent, so ids come from
  the `/wiki/` article page (`wgWikibaseItemId`). Seeds get theirs at corpus collection; other
  concepts best-effort (≤ 1 request/s, 10-minute cap, Gemini confirms the page matches).
- Embeddings: `MODEL_EMBED` (gemini-embedding-001, 256 dims), no fallback model.
- **Entity linking** (at ingest and in the build's re-link): exact label/alias match first (any
  demand type). Otherwise, for concept and term demands only, embed the demand label; concepts
  whose label embedding reaches `LINK_THRESHOLD` become candidates (top 5), and `link_confirm`
  (MODEL_QUALITY) picks one or none. The threshold is recalibrated on every build to keep 95% of
  true matches, measured on exact-alias matches whose wording differs from the concept label,
  and written to `.env.example` (0.865 after M2.1). Embedding similarity alone can't separate
  a concept from its near neighbours (95% precision would need cosine 0.98), so the model
  decides; MODEL_QUALITY measured 95% precision vs 89% for MODEL_FAST.
  Anything else is `unlinked` (still usable as a term demand).
- **Held-out evaluation.** Coverage on the corpus the graph was built from is inflated
  (single-article concepts are made from those very mentions), so linker quality is measured on
  `data/heldout_urls.txt`: 15 fresh articles from the same feeds, ingested through the production
  path and reported by `scripts.eval_heldout`. **Rule:** held-out articles are never added to the
  corpus or used to build the graph; `build_concepts` refuses to run if the two lists overlap.
  The held-out number is the one to quote (M2.1: 57% exact-name, 5% model-confirmed, 38%
  unlinked).

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
users/{uid}/demo_graphs/{persona}             a demo reader's graph for one persona (below)
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
- Calibration: 8 items, round-robin over the interest domains (all four if none); within a
  domain, among its 150 highest-`doc_freq` concepts, the one with b closest to θ, never one already
  asked (deterministic). Answers: explain +3.0, **heard −1.5**, none −3.0 (`calibration_answer`),
  and an Elo step with K = 0.3 and outcome explain 1, **heard 0.5**, none 0. Only the current item
  can be answered; "Skip" ends calibration with what was answered.

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
   a `user_ingested` page), else shows the concept definition.
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
| POST | /v1/content | `{url}` (server fetches via safe_fetch) or `{url, title, paragraphs[]}` (extension, already extracted and redacted) → `{content_id, title, paragraphs}`; ingests if new. Requires auth and the per-user daily cap; disabled in prod until both are in place |
| GET | /v1/content?q=&persona=&density= | library list: `{id, title, site, word_count, description, author, published, image, domain, concepts_new}`; `domain` = graph domain with the most linked salience; `concepts_new` = span annotations this reader would get |
| GET | /v1/content/{id} | article for rendering: metadata + `paragraphs[{id, text}]` + `status: ready \| analysing` (a pending article, §3; annotations and recommendations answer 409 until it is ready) |
| POST | /v1/content/{id}/analyse | phase 2 of "Open here" (§3): 200 `{status: ready}` (no LLM call if already analysed), 202 `{status: analysing}` while another request holds the lease, 410 after 3 failed analyses, 504 on the 120 s timeout; no ingest slot (taken in phase 1) |
| GET | /v1/content/{id}/recommendations?prefer= | Up next (§16): up to 6 items, `pending` while web lookups run |
| POST | /v1/recs/events | `{events: [{id, type: rec_shown\|rec_clicked\|rec_dismissed\|rec_completed, item_id}]}` → `{applied, ignored}`; idempotent by event id |
| POST | /v1/recs/open | `{url}` → `{content_id, new, ready}`: phase 1 of ingesting a web recommendation via safe_fetch as `user_ingested` (§3), within the per-user daily cap (429 past it); `ready: false` until POST .../analyse completes |
| GET | /v1/me/export | everything we hold about the caller, as JSON |
| DELETE | /v1/me | delete all of the caller's data and their Auth user |
| GET | /v1/content/{id}/annotations | ranked, budgeted annotations for the caller |
| POST | /v1/explain | `{content_id, demand_id?, paragraph_id?}` → `{id, kind: verified\|definition, mode, label, definition, background, author_says, analogy_domain, band, thinks_in, style, cached, prompt_version}` (§7) |
| POST | /v1/explain/{id}/report | `{event_id, content_id, concept_id?}` → `{evicted, event_applied}`: "This is wrong" (§7) |
| POST | /v1/events | `{events: [{id, type, at, concept_id?, content_id?, paragraph_id?, words?, ms?}], persona?}` → `{applied, events_applied, events_ignored}`; sync, idempotent by event id (stored at `users/{uid}/events/{id}` with `expire_at` for the 90-day TTL); `applied: false` and no writes while learning is paused |
| GET | /v1/me/graph | concepts by domain with band, plus stats (concepts learned, annotation trend); `?domain=X[&q=]` → capped subgraph for the knowledge map (§15.2) |
| PATCH | /v1/me/graph/{concept_id} | user correction ("I know this" / "I don't") → strong evidence |
| GET | /v1/me/profile | reading profile page data: summary, domains, THINKS_IN, weekly band changes, trend (§15.2) |
| PATCH | /v1/me/settings | `thinks_in`, `density`, `explanation_style`, `learning_paused` |
| POST | /v1/me/profile/edits | parse a natural-language profile edit → preview, writes nothing (§15.3) |
| POST | /v1/me/profile/edits/{id}/apply | apply a previewed edit |
| POST | /v1/me/profile/edits/{id}/undo | undo an applied edit |
| POST | /v1/me/consent | `{version}` (signed-in readers): records consent; required before anything is recorded (§11.4) |
| POST | /v1/onboarding | field, interests, comfort per domain, ≤ 3 frames, ≤ 3 liked library content ids (§4); needs consent |
| GET | /v1/calibration/next | next item: concept with b closest to current θ, not yet asked; `{done}` after 8 |
| POST | /v1/calibration/answer | `{concept_id, answer: explain|heard|none}`: only the current item (409 otherwise) |
| POST | /v1/calibration/skip | ends calibration (onboarding done) |
| GET | /v1/me/profile/edits | the last 10 applied/undone edits (expired pending ones are deleted) |
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
- Span: dotted underline; hover (desktop) / tap (mobile) opens card; card has "Knew this",
  "Helpful", "This is wrong". Card label: "Explanation — not the author's words".
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
  definition.
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
- Consent screen at onboarding states what is collected and why, in plain language. The API
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
  10 profile-edit parses/day (§15.3), 120 requests/min overall, 30 event batches/min.
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
   THINKS_IN domains, and this week's band changes. θ (rounded to one decimal, as the page shows it) maps to words: θ ≥ 1 "advanced",
   0 ≤ θ < 1 "comfortable", −1 ≤ θ < 0 "building", θ < −1 "new to". Example:
   "Comfortable in finance, building in economics. You think in software. 6 concepts moved up a
   band this week." Only domains the reader rated, reads in or has concepts in are named (M7).
   Same inputs always give the same text (unit-tested).
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
  history, the current article) is ever part of a query (tested).
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
  the per-user daily cap) and **Open original**. Videos and podcasts open the original in a new
  tab. "Open here" moves to two-phase loading (article first, annotations after) in the rest of
  M6.
- Events `rec_shown`, `rec_clicked`, `rec_dismissed`, `rec_completed` (a recommended library
  article read to the end) update format stats, relation dismissals and seen items.
- Storage (M3): `users/{uid}/rec_signals/{persona|default}` and `users/{uid}/ingest_counts/{day}`
  (§4), covered by export and delete. Personas apply to anonymous demo readers only; signed-in
  readers use `default` and a neutral format prior until onboarding (M7).

