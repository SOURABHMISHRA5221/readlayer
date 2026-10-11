# Landing and onboarding (decision 41)

## Context

The Design pass (Gloss) is merged and live (#22–#24). Decision 41 (BUILD_PLAN "Landing and
onboarding", all required) adds, before M8: a landing page at "/" for signed-out visitors that
explains problem, failure of existing options, solution and trust in under 30 seconds with a live
mini-demo; and onboarding in 2 screens that visibly uses the web to understand the reader,
replacing consent → field → interests → comfort → frames → liked articles → 8 calibration taps.
The privacy rule stays absolute: free text is never sent to search or to an LLM as-is and is
never stored.

**Demo data (2026-10-11):** no paragraph was fully cached; Sourabh approved warming the best one
(markets article p5, "Basis points" and "Monetary tightening" at unaware / heard of / can explain).
`build_landing_demo.py --paragraph 23324188:p5 --warm` generated the 5 cards through the normal
verified path (all verified; production spend $0.0778 → $0.1081, $0.03), confirmed them as cache
hits through the API and wrote `apps/web/src/landing/demo.json`; both temporary readers deleted.

**Decision 42 (Sourabh, 2026-10-11): topic fallback for unmatched free text** (replaces the open
question). In `POST /v1/onboarding/resolve`, a piece that matches no concept (after whole-piece and
" and " lookups and `resolve_names`) goes:
1. through a small deterministic alias list in code (`ONBOARDING_TOPIC_ALIASES`: F1, Formula 1,
   Formula One, IPL, NBA, … → sports; startups, startup, VC, venture capital → business; …), casefold
   exact match, no model call;
2. else **only the redacted phrase** is embedded (`llm.embed`, MODEL_EMBED; no uid or reader data;
   not stored; never sent to search) and compared with the embeddings of the 14 topics' scope lines
   (cached in memory per process); the nearest topic is returned if its cosine similarity is ≥
   `ONBOARDING_TOPIC_THRESHOLD`, set from a committed labelled set
   (`apps/api/evals/cases/onboarding_topics.yaml`, ~24 phrases with expected topic or "none",
   committed before choosing the threshold; precision reported in the PR, decision 26); below it,
   "didn't recognise".
The response's `topics` field carries `[{phrase_index, topic, via: "alias" | "embedding"}]`; screen
1 shows "F1 → Sports" with a select to change or drop it; the chosen topics join the topic chips. The
consent sentence (consent-v2) adds: "What you type is matched to topics by our model and isn't
stored." DESIGN §11 records the exception. Tests: the alias path makes no model call; the embedding
path receives only the redacted phrase; no raw free text in any search request, log record or stored
document.

## Dates and checkpoints

Today is Oct 11 (IST). This milestone runs Oct 12–13; M8-local Oct 14, M9 Oct 15, freeze Oct 16.
1. **Oct 12:** landing page (A), privacy page, demo data, eval numbers, first-paint work.
2. **Oct 12–13:** onboarding API (C) and the 2 screens (B).
3. **Oct 13:** acceptance, screenshots, Lighthouse, docs, reviews, merge, deploy, live check.

**Checkpoint 1, end of Oct 12 IST:** landing page not done → ask Sourabh what to cut.
**Checkpoint 2, end of Oct 13 IST:** milestone not merged → ask before touching M8's day.
Candidates to name (not to cut): the step-4 map animation, the side-by-side in section 3, the
readback's Edit link, podcast cards in onboarding. Nothing is cut without his answer.
STATUS §9 gets these dates and both checkpoints.

## A. Landing page (apps/web)

1. **Routing and the signed-in hint.**
   - `readlayer:signed-in` in localStorage (existing key style, as `readlayer:theme`) is set
     whenever auth reports a session (sign-in or restore, so today's readers get it on their next
     visit) and cleared on sign-out, End demo and account delete.
   - "/" without a session shows `LandingPage` (lazy). With a session: the feed, as today.
   - Signed-out deep links (`/read/<id>`, `/profile`, `/for-you`) show the landing with a small
     line "Sign in or try the demo to open that page" and, after sign-in or the demo CTA, return to
     the requested path (kept in `sessionStorage`, path only). `SignInPage` is deleted; its demo
     persona picker moves into the landing CTA (A4).
   - `/privacy` is public and also works for signed-in readers (lazy chunk); from onboarding it opens
     in a new tab so screen-1 choices survive.
2. **First paint without flash or shift.**
   - `index.html` carries a static hero (headline, subline, the two CTAs, the demo's paragraph text
     in a fixed-size box) inside `#root`, styled by a small inline critical CSS block that covers
     light, dark (`[data-theme]` and `prefers-color-scheme`) and both widths.
   - `public/theme-init.js` (runs before first paint) shows that static hero **only on "/" with no
     signed-in hint**; otherwise it sets a class that shows the neutral loading shell instead, so
     `/read/<id>`, `/profile`, `/privacy` and returning readers never see a landing flash.
   - A `HeroStatic` component with identical markup is in the main bundle; the app renders it while
     auth loads (no hint) and as the landing chunk's Suspense fallback, so React replaces the static
     hero with the same pixels. The demo mounts into the fixed box (no shift).
   - Fonts: the Google Fonts stylesheet loads non-blocking on the landing (preload + swap to
     stylesheet on load) with the existing metric-matched fallbacks; the font files the note card
     uses (Schibsted Grotesk 400/600/700, Source Serif 4 400 and italic) are preloaded so opening a
     note fetches nothing.
   - Acceptance adds CLS < 0.1 and screenshots of a signed-in reload on "/", `/read/<id>` and
     `/privacy` showing no landing flash.
3. **Sections and copy** as BUILD_PLAN A1–A8 (meaning and tone kept; wording adjusted only for
   accuracy):
   - **Hero** with the live mini-demo (A4), CTAs "Try it as a demo reader" and "Sign in with Google".
   - **Problem**: three cards with small inline SVG illustrations, the closing line, no statistics
     (none of the drafts cite a source).
   - **Solution**: the sentence and a static side-by-side of the same paragraph for the newcomer
     and the trader from the demo data; the caption's counts are whatever the data shows.
   - **How it works**: 4 numbered steps (Margo idle / think / idle / happy); step 4 is a small SVG map
     where 3 nodes fill in when scrolled into view (CSS only; static under reduced motion).
   - **Trust**: "Never changes the original"; "Every explanation is verified" with the eval numbers
     (A5) and a link to the README's evaluation section; **"Your reading stays yours"** reworded for
     accuracy, since article paragraphs (pasted pages included) do go to Gemini: "The AI never
     learns who you are or what you've read: it sees only the paragraph it explains, a reading level
     and your analogy style. Export or delete everything anytime."
   - **What you can read**: articles with notes; YouTube videos and podcasts in your feed (no notes
     on them today); any pasted link with notes. **The browser extension is not listed** (not live:
     unpacked, not public). STATUS §4 row "Resolve in: M8-local", and BUILD_PLAN M8-local acceptance
     gains "the landing lists the extension once it works unpacked".
   - **Final CTA band** (Margo happy) and **footer** (wordmark, "Built on Gemini and Google Cloud",
     GitHub link, privacy link).
   - Margo only in hero, how-it-works, trust (one small idle mark) and final CTA.
4. **Live mini-demo.**
   - One real paragraph from a demo article where the three personas differ (terms, frames, bands).
     The toggle labels describe the personas' frames and the JSON maps them: **"Software engineer" =
     newcomer (software), "Cricket fan" = trader (cricket), "Policy student" = policy student
     (law)**. The demo CTA signs in as the selected persona, and the persona chip in the app shows
     "Newcomer (software engineer)" / "Markets trader (cricket fan)" / "Policy student", so the names
     line up.
   - Static JSON `src/landing/demo.json`: paragraph, per persona the span annotations (anchor, label,
     definition, prerequisites, level, band) and each span's verified explanation (background,
     author_says, analogy_domain, band). Rendered with the real annotator (`createAnnotator` with
     `loadExplanation` from the JSON); the toggle is a radiogroup (arrow keys) calling `update()`.
   - **Card actions on the landing**: a new annotator option `actions: "full" | "demo"` (default
     "full", so the reader and extension are unchanged); "demo" replaces Knew this / Helpful / This
     is wrong with one "Try it on any article" link to the demo CTA. `ANNOTATOR_VERSION` bump and a
     vitest.
   - **No network after load, defined:** while toggling and opening notes, zero fetch/XHR and zero
     requests to the API, Firebase or any non-static origin (fonts are preloaded; the annotator has
     no `onEvent` here). Checked with the CDP network log.
   - **Build script** `apps/api/scripts/build_landing_demo.py` (dry run first):
     1. read-only with ADC: the demo article and, for each persona's band/frame/style, the expected
        `explanations/{key}` documents, with ids computed by **importing the explain service's own
        key functions** (never re-derived); **abort before any request if one is missing**;
     2. then, as a temporary anonymous reader: annotations per persona and `POST /v1/explain` (all
        cache hits by step 1; it still stops at the first non-`cached`/non-`verified` response);
     3. writes the JSON; deletes the reader in `finally`.
     Production writes, listed by the dry run: 1 anonymous Auth user (created, deleted); the docs the
     annotations GET writes for it (removed by `DELETE /v1/me`); `ops/explain/days/{date}` hit
     counters (+N, not reversible).
5. **Eval numbers.** `apps/web/scripts/eval-numbers.mjs` reads the "Judge comparison" table of
   `apps/api/evals/report.md`, **fails unless exactly one judge row** exists, and writes `src/landing/evals.json` (adversarial rejected, good accepted,
   injections safe, as "15 of 15"); the JSON is **generated and committed**, the web build runs the
   generator first, and a vitest runs the generator and compares, so a stale copy fails CI. Never
   rounded.
6. **Budgets.** BUILD_PLAN says "landing JS chunk under 60 KB gzip": that is the landing chunk
   (code + demo/eval JSON). The main bundle (143.6 KB today, Firebase included) also loads on "/";
   the acceptance log reports **total JS on "/"** next to the chunk, STATUS §4 records the
   interpretation, and the PR points it out to Sourabh. Added to main: the hint logic, `HeroStatic`,
   routing (small); `PrivacyPage` and `LandingPage` are lazy; main stays < 150 KB.
7. **Lighthouse.** Run with a pinned `pnpm dlx lighthouse@12.8.2` (no dependency, lockfile or CI
   change; STATUS §4's M6 row "no Lighthouse install" stays true) against `vite preview` of the
   production build and against the live site after deploy, mobile preset: LCP < 2.5 s, CLS < 0.1,
   accessibility 100. CI does not run it.

## B. Onboarding in 2 screens (apps/web `WelcomePage`, rewritten)

Demo readers skip onboarding (as today).

**Screen 1 "Tell Margo about you"**:
- Field: one chip row (existing `Field` values); choosing one preselects its suggested frame
  (frames stay editable on the profile).
- Topics: taxonomy chips (multi-select).
- "Anything else you follow?" free text (≤ 120 chars), held **only in React state** (never
  localStorage, sessionStorage or the URL; vitest).
- Consent inline: a checkbox with one plain sentence and a "What we store" link (`/privacy`, new
  tab). The sentence is new text, recorded as **`consent-v2`** (added to `CONSENT_VERSIONS`; v1 stays
  valid). Continue is disabled until it is ticked.
- **Order on Continue:** `POST /v1/me/consent` (v2) → if the free text is non-empty,
  `POST /v1/onboarding/resolve` and the screen **stays** showing recognised concepts as removable
  chips and "Didn't recognise: …", with Continue again to move on → `POST /v1/onboarding`
  (field, interests = topics + resolved concepts' domains, thinks_in = the field's frame). Nothing
  is resolved or recorded before consent.
- Margo (idle): "Pick a few, I'll find the rest."

**Screen 2 "Here's what's out there for you"**:
- Cards from `POST /v1/onboarding/discover` (C3), re-asked while `pending`, Margo (think) while
  loading; 6–9 cards.
- Each card: "I'd read this" / "Not for me" (`pick`, C4) and one highlighted term "Know this? Yes /
  Not really" (`know`, C5); all buttons keyboard-reachable, 44px.
- After 5+ answers, Margo (happy) reads back one deterministic sentence from the answers and frame
  (pure helper, tested), with "Edit" (back to screen 1, choices kept; see C4 for what Edit keeps).
- "Start reading" → `POST /v1/onboarding/finish` → For you.
- **Resume:** `_onboarding_step` gains `"discover"` (after `POST /v1/onboarding`, before finish);
  WelcomePage resumes on screen 2; `post_onboarding` returns `next: "discover"`. The old comfort,
  frames, liked-articles and calibration screens are removed from the web; the calibration API stays.

## C. API (apps/api) — privacy rule absolute

1. **Free text.** Only inside `POST /v1/onboarding/resolve`: redacted (`privacy/redact.py`), split
   on commas into ≤ 5 pieces of ≤ 40 chars; each piece is **looked up whole first** (exact
   label/alias, no model call); only a piece with no exact match is split on " and " and looked up
   again; remaining misses go to `resolve_names` (embedding candidates + `link_confirm`), which
   receives **only individual redacted pieces**, never the full text, as goals do. Response:
   recognised concepts and unrecognised pieces (echoed to the same client only). Nothing of the text
   is stored or logged (logs: `uid_hash`, counts, cost).
   - Uses `consented_user` (409 `consent_required` before consent, the existing onboarding status);
     demo readers 403. `ONBOARDING_RESOLVE_DAILY_CAP` 5 per reader per day
     (`onboarding_resolve_counts/{day}`, in `USER_SUBCOLLECTIONS`).
   - Live check of the BUILD_PLAN example, done 2026-10-11 read-only: "F1", "startups", "Indian
     politics", "Formula One" do not resolve (see the open question); "mergers and acquisitions"
     resolves whole to M&A (so " and " splitting only applies after a whole-piece miss).
2. `POST /v1/onboarding/resolve {text}` → `{concepts: [{id, label, domain}], topics: [domain],
   unrecognised: [str]}` (`topics` stays empty unless the open question's fallback is approved).
3. `POST /v1/onboarding/discover {topics: [domain ≤ 6], concepts: [concept id ≤ 2]}` →
   `{items, pending}`; consented signed-in readers only.
   - Concept ids must exist in the graph (else 422), at most 2, **articles only** for concepts.
   - `FeedSearch.gather` is generalised to (key, query, keep) entries so topic keys and concept keys
     (`feed:c:<concept_id>:<day>`, query = concept label + the article phrase) share in-flight
     de-duplication, the per-instance limit, the backoff and the yesterday fallback; concept results
     are filtered on the concept's label or aliases (not `keep_for(topic)`).
   - Caps: everything counts against `FEED_SEARCH_DAILY_CAP` and the global caps; a shared daily
     sub-cap for concept searches `ONBOARDING_CONCEPT_SEARCH_DAILY_CAP` 20 (of the 60); a per-reader
     counter `onboarding_discover_counts/{day}` (in `USER_SUBCOLLECTIONS`, limit 3), where only calls
     that start new searches count (re-asks that join in-flight ones don't).
   - Fallbacks on failure or a cap: today's or yesterday's cached entries, then library items for
     those domains (corpus, visibility-filtered).
   - Served items are recorded in rec_signals (relation `feed`) so the feed signals apply to them.
   - **Know term per item**, stable across re-asks: stored with the served item (item id → concept
     id) the first time the item is served; chosen among the graph concepts the item names
     (`named_concepts`), excluding the resolved concepts sent to discover (≤ 2) and already offered ones, the
     one whose `base_difficulty` is closest to the reader's θ in its domain. An item naming no concept
     gets no term (pick buttons only). Offered ids ≤ 12.
   - Mix: up to 9 items, at least one per chosen topic/concept where available, articles first.
   - DESIGN §17's search bound and the live-check count include concept searches (≤ 18 topic +
     ≤ 2 concept searches per onboarding, ≤ 20 concept searches a day overall).
4. `POST /v1/onboarding/pick {item_id, liked}` → the topic comes from the **served item** (unknown
   item 404); one pick per item, ≤ 9 per reader; applies the feed signal (`rec_clicked` /
   `rec_dismissed`) and an interest delta for that domain (+0.15 / −0.15, clamped), stored as a
   delta (`onboarding_picks`) so **Edit → Continue re-applies the picks on top of the new chosen
   topics** instead of erasing them; offered and answered terms are kept across Edit.
   - Observable effect for acceptance (chosen topics start at 1.0, so "I'd read this" can't raise
     them): two "Not for me" on topic X lower X by 0.30 and move X behind the other chosen topics in
     the feed's topic order.
5. `POST /v1/onboarding/know {concept_id, known}` → only an offered id, **each answered once**, ≤ 9
   per reader, refused once onboarding is done; a new repo method counts and writes the edge and θ
   in one transaction (not `calibration_answer`, which caps at 8 and sets onboarding done);
   `apply_answer` with Yes → "explain", Not really → "none" (the calibration Beta evidence and
   onboarding-strength Elo step).
6. `POST /v1/onboarding/finish` → marks onboarding done and clears the offered/answered lists.
7. **Every new route** uses `consented_user` (409 `consent_required` before consent); demo
   readers 403.
8. **New user data:** `onboarding_offered` (item → concept), `onboarding_answered`,
   `onboarding_picks` declared on `UserProfile` (so `model_dump()` writes keep them; export/delete
   via the user doc); `onboarding_resolve_counts`, `onboarding_discover_counts` in
   `USER_SUBCOLLECTIONS` (test). `/privacy` lists every stored item, including these.

## Tests (offline)

- pytest:
  - resolve: (a) no search request contains any piece or the raw text; (b) embedding and
    `link_confirm` receive only individual redacted pieces with no exact match, never the full text,
    and an email or phone number arrives as `[REDACTED:…]`; (c) no log record (caplog, all loggers at
    DEBUG including `app.llm`) and no document in the fake store contains any piece; (d) an exact
    match makes zero embedding or LLM calls; whole-piece lookup before " and " splitting; cap; consent
    and demo guards;
  - discover: queries are only taxonomy or concept labels plus fixed phrases (property test); shared
    cache (a second reader makes no new search); concept ids validated and ≤ 2; sub-cap and
    per-reader counter (re-asks free); fallbacks; served items recorded; know terms stable across
    re-asks, exclusions, ≤ 12, items without a term;
  - pick: topic from the served item, once per item, ≤ 9, interest delta and rec signal, deltas
    re-applied after a second `POST /v1/onboarding`; know: offered only, once each, ≤ 9, done →
    refused, same edge and θ as `apply_answer`; finish; `_onboarding_step` "discover"; data rights.
- vitest: landing toggle changes marks per persona and opens a card from the JSON with `fetch`
  stubbed to fail; demo card actions; eval-numbers generator vs report; readback helper; free text
  only in React state; Continue disabled until consent; persona label mapping.
- `pnpm -r typecheck`, `uv run ruff check .`, `uv run pytest -q`, web build (budgets).

## Acceptance (run, not assumed)

1. Mobile (390): problem and solution understood without scrolling past section 3; before/after
   screenshots (1440 and 390, light and dark) of "/" (before = the current sign-in landing, already
   in `docs/evidence/landing/before/`), the onboarding screens (before = the old welcome steps) and
   `/privacy`, in the log.
2. Landing demo: for all 3 personas the toggle changes highlights, analogy and depth; zero
   fetch/XHR and no API/Firebase/non-static requests while toggling and opening notes.
3. No flash: signed-in reload on "/", `/read/<id>` and `/privacy` shows no landing (screenshots).
4. New Google reader on the harness: 2 screens to the feed in under 90 s (timed); two "Not for me"
   on one topic move it behind the others in the feed's topic order; know answers show as band
   changes on the profile.
5. Free text "F1, startups": outbound search requests contain only concept/taxonomy labels plus
   fixed phrases (test and harness search log); nothing of the text in the emulator Firestore dump or
   the logs.
6. Lighthouse mobile (local production build and live): LCP < 2.5 s, CLS < 0.1, accessibility 100;
   axe 0 (**every impact level**, not only serious/critical) on "/", `/privacy`, onboarding screens 1
   and 2, at 1440/390, light and dark; keyboard path through the demo toggle, highlights, card and
   screen-2 buttons; landing chunk < 60 KB gzip with total JS on "/" reported.
7. DESIGN (§4 onboarding, §8 new routes, §11.4 consent v2 and the free-text rule in the same words
   as the tests, §17 feed search bounds, new §20 landing), STATUS (§4 rows, §9 dates and
   checkpoints, acceptance), BUILD_PLAN (M8-local extension line).

## Production data writes

- `build_landing_demo.py`: as listed in A4 (1 temporary Auth user deleted; its docs deleted; hit
  counters +N); refuses before any request if an explanation entry is missing.
- Live check after deploy: landing (Lighthouse, no-network demo) as an anonymous visitor (no writes);
  onboarding on a Google account by Sourabh (his own data; ≤ 18 topic + ≤ 2 concept searches; ≤ 1
  resolve, which may call `link_confirm` once, ≈ $0.002).

## Ship

PR "Landing and onboarding: …", milestone-reviewer SHIP, merge on green CI, deploy API then web
(each through the normal permission prompt), live check, STATUS, DESIGN, AUTOPILOT_LOG with
before/after paths.

## Critical files

Web: `index.html`, `public/theme-init.js`, `src/App.tsx`, `src/lib/auth.ts` (hint), new
`src/pages/LandingPage.tsx`, `src/landing/*` (HeroStatic, sections, demo.json, evals.json),
`src/pages/PrivacyPage.tsx`, `src/pages/WelcomePage.tsx` (rewritten), `src/lib/onboardingApi.ts`,
`scripts/eval-numbers.mjs`, styles; delete `src/pages/SignInPage.tsx`. Annotator: `card.ts`,
`index.ts`, `types.ts` (demo actions). API: `app/me/onboarding.py`, `app/me/router.py`
(`_onboarding_step`, consent v2), `app/reader/onboarding.py`, `app/recs/feed.py` (generalised
gather, concept keys), `app/recs/web_search.py` (sub-cap), `app/store/reader_repo.py`,
`app/reader/state.py` (`UserProfile` fields), `scripts/build_landing_demo.py`.

## Amendment: decision 44, landing visuals (Sourabh, 2026-10-11)

Sourabh reviewed the built landing (commit 765726d, screenshots in the log). **Keep** structure,
copy, headline, the Read-as demo and "Same article. Different help." **Fix the lack of visuals.**
Also: light is the default theme (done in this branch: dark only via the toggle, the OS setting is
no longer followed), and the GitHub links stay (repo goes public at submission after a gitleaks
scan, added to M9). Built as part 0 of the landing (before §C/§B), same checkpoint 1 (end of Oct 12).

### V1. Margo as a character (hero and final CTA)
- New `MargoHero` SVG (same body, outline, fold, swipe and moods as `Margo`, plus one arm and a
  small note card in the hand, held out toward the demo sheet as if handing over the note).
  Inline SVG, aria-hidden, in `HeroStatic` too (so in index.html: no shift, no request, not the
  LCP image). ~200px at ≥1024 (beside the sheet, overlapping its lower corner, arm reaching to
  the paragraph), ~120px below 1024 (beside the "Read as" row, arm pointing down at the sheet).
- Mood follows the toggle: Software engineer → think (2 new ideas), Cricket fan → idle (1 new,
  1 refresher), Policy student → happy (1 note); a fixed map in `demoPersonas.ts` (vitest). The
  static first paint shows the default persona's mood. Mood changes are a cross-fade of eyes and
  mouth (opacity only); none under reduced motion.
- Final CTA: the same `MargoHero` (happy), ~180px desktop / 120px mobile.
- The small sheet-margin Margo, the step glyph Margos and the trust mark are removed; the only
  small Margo left is the wordmark.

### V2. Product shot (below the hero)
- A laptop frame and a phone frame drawn in CSS/inline SVG (no stock art) holding real
  screenshots of the reader: desktop 1440×900 with the "bps" note open as a sidenote; phone
  390×844 with the bottom-sheet card. Demo persona Newcomer on the demo markets article
  (`2332418841…`), cropped to the paragraph and its note (a short snippet), caption
  "Gloss on an Economic Times article. The article's words are unchanged; the note is ours."
- Captured by `tools/shots/landing_media.py` from the **live** site as an anonymous demo reader
  (deleted after with `DELETE /v1/me`), at deviceScaleFactor 2; encoded to AVIF (ffmpeg) and WebP
  (cwebp) at 1x and 2x in `apps/web/public/landing/` (static files, not bundled), `<picture>` with
  explicit width/height, `loading="lazy"`, `decoding="async"`, alt text describing what is shown.
- Mobile: the phone frame only, below the fold.

### V3. Problem illustrations (Gemini image model on Vertex)
- Model Garden check (2026-10-11): no Imagen listed; Gemini image models
  `gemini-3.1-flash-image` (GA, $0.0672/image on Vertex per LiteLLM's cost map),
  `gemini-3-pro-image` ($0.134), `gemini-3.1-flash-lite-image` ($0.0336). Use
  **`gemini-3.1-flash-image`** via a new `MODEL_IMAGE` env var (never hard-coded).
- `app/llm.py` gains `generate_image(task, prompt_vars, reference_png)`: LiteLLM completion with
  image output and the Margo PNG as reference input; if LiteLLM can't return images for this
  model, `google-genai` is added and called **inside llm.py only**. Same budget check, retries,
  cost logging and spend ledger as other calls; prompt in `app/prompts/landing_art.md` (version
  header). No article text, no reader data in the prompt.
- `apps/api/scripts/landing_art.py --dry-run` prints scenes, variants and the cost estimate; the
  real run makes **≤ 3 variants × 3 scenes (+ ≤ 3 re-rolls) = ≤ 12 images, hard stop at $1.00**
  (≈ $0.60 expected; more than "a few cents", so it is reported to Sourabh). Outputs go to the
  scratchpad; the chosen three are post-processed (white → transparent, two-tone kept) and
  encoded to WebP (cwebp) at 1x/2x (~320px and 640px wide) in `apps/web/public/landing/`.
- Scenes: (a) Margo-style reader frowning at a paragraph of jargon; (b) a laptop with a dozen tabs
  bursting out; (c) a shredder turning an article into a three-line summary. Flat, ink + teal only,
  no text in the image.
- Dark theme: transparent background and `filter: invert(1) hue-rotate(180deg)` (ink → light,
  teal stays teal); checked in the dark screenshots.
- `<img>` with alt text (meaningful, they illustrate the three problems), lazy, explicit size.
- Footer credit: "Illustrations made with Google's image model." DESIGN §20 and STATUS §7 record
  model, prompts (by file and version) and the actual cost.

### V4. How it works: 2×2 grid of looping clips
- Four 3–5 s silent clips recorded from the **live** reader by `tools/shots/landing_media.py`
  (CDP screencast on a second connection, frames → ffmpeg), same temporary demo reader:
  1. tap a highlight → the note slides in;
  2. "Say it simpler" → the simpler Background replaces it;
  3. "Know this?" → "Not really" → the term becomes a highlighted note (what the app does today;
     the step text says so, not "added to path");
  4. the knowledge map gains nodes (profile map before and after marking terms "Knew this").
- Each: WebM (VP9) + MP4 (H.264), ≤ 400 KB, ~640px wide, WebP poster; `muted autoplay loop
  playsinline preload="none"`, `src` set only when the clip scrolls near view
  (IntersectionObserver); under `prefers-reduced-motion` only the poster `<img>` is rendered
  (vitest on the component's choice). Video is decorative next to the step text: `aria-hidden`
  on the video, the poster image has an empty alt.
- Layout: 2×2 grid ≥768px (one column below), large clip on top, number + title + text under it.
- `GrowingMap` is removed (the clip shows the real map); the page's one orchestrated animation is
  now the clips, which are recordings, not UI motion.

### V5. Rhythm
- Full-bleed section bands alternate paper / wash (hero paper, problem wash, solution paper with
  its wash comparison panel switched to surface, how-it-works wash, trust teal, formats paper,
  final CTA wash).
- Trust is one full-width teal band (`--accent` background, `--on-accent` text, both themes
  contrast-checked by axe): title, three statements, and the eval results as large figures from
  evals.json ("15/15 broken explanations caught", "24/25 good ones accepted", "10/10 injection
  attempts resisted"), never rounded, with the "How we test" link.

### V6. Budgets and checks
- LCP < 2.5 s mobile (hero text and inline SVG only; nothing above the fold is an image);
  first view (hero, 390×844) transfers < 1.5 MB, reported from resource timing; everything below
  the fold lazy (images `loading="lazy"`, videos without `src` until near view).
- Landing chunk stays < 60 KB gzip (media are static files, not in the chunk); main < 150 KB.
- axe 0 at every impact (1440/390, light/dark), alt text on meaningful images, decorative
  aria-hidden; `tools/shots/landing.py` extended: first-view bytes, lazy media not requested
  before scroll, clip sizes ≤ 400 KB (also a vitest over `public/landing/` file sizes).

### V7. Production writes and spend (this amendment)
- `landing_art.py`: ≤ 12 image calls, ≤ $1.00, counted in the daily LLM ledger; nothing stored
  in Firestore beyond the ledger.
- `landing_media.py` on the live site: 1 anonymous Auth user and its docs (deleted with
  `DELETE /v1/me`), explain hit counters (+N, not reversible), at most 2 "Say it simpler"
  generations if not cached (≈ $0.01), 1 "Know this?" answer and ≤ 3 "Knew this" in the demo
  graph (deleted with the reader).

### V8. Docs
- STATUS §10 decision 44; BUILD_PLAN landing section (visuals) and M9 (repo public at submission
  after a gitleaks scan); DESIGN §19 (light default) and §20 (landing visuals, image model,
  prompts, cost); README third-party credit unchanged except the illustration line.

### Amendment round 1 (plan-reviewer REVISE, 9 items; all applied, these override V1–V8)
1. **Spend needs Sourabh's yes.** `landing_art.py --dry-run` prints scenes, variants and the
   estimate; the real run waits for Sourabh's explicit yes, recorded in AUTOPILOT_LOG. Default
   3 scenes × 2 variants + ≤ 2 re-rolls = **≤ 8 images, hard stop $0.60**; more needs his yes.
2. **The cap doesn't trust LiteLLM pricing.** `generate_image` charges images ×
   `MODEL_IMAGE_PRICE_USD` (new setting, default 0.0672) whenever `completion_cost` is missing or
   0, on both the LiteLLM and google-genai paths. The script counts images itself and stops before
   the call that would cross the cap.
3. **`generate_image` contract in llm.py.** Route `"landing_art": Route("model_image", None)`,
   explicitly no fallback (Gemma can't make images). Output validation replaces the Pydantic
   schema: exactly one decodable PNG/JPEG ≥ 512×512 (Pillow), else retry with backoff, then
   raise. Returns bytes + model + prompt version + cost; the version goes to DESIGN §20.
4. **Offline tests** (fake LiteLLM / google-genai, `InMemorySpendStore`, no network): refuses
   over budget; missing/invalid image retried then raises; per-image cost recorded when
   `completion_cost` gives nothing; the prompt holds only the scene variables (no article or reader
   fields); `landing_art.py`'s cap stops at the limit.
5. **Reference image.** The Margo SVG (idle) is rasterised by headless Chrome (`tools/shots/cdp`,
   `Page.captureScreenshot` of the inline SVG) to a 512×512 PNG in the scratchpad, never
   committed.
6. **Where spend lands, headroom first.** The ledger is production Firestore
   `ops/spend/days/{date}`; before the real run the script reads today's spend and refuses if
   spend + cap > $8 (`LLM_DAILY_BUDGET_USD`), as STATUS §9 step (5) did.
7. **`landing_media.py --dry-run`** (read-only): checks that the Newcomer "bps" Background and
   its "Say it simpler" (band − 1) entry on `2332418841…` are cached (keys from the explain
   service's own functions, as `build_landing_demo.py` does); prints the exact steps and writes:
   1 anonymous Auth user and its reader docs (removed by `DELETE /v1/me`, which also deletes the
   Auth user: `app/me/router.py` → `delete_user`), explain hit counters as an exact N, 1 "Know
   this?" answer, ≤ 3 "Knew this"; generations: 0 if both are cached, else the count (≈ $0.005 each).
8. **Pause control (WCAG 2.2.2).** Clips loop while on screen, pause when they leave the viewport
   (IntersectionObserver), and each has a visible 44px Pause/Play button (`aria-pressed`,
   labelled per clip). Reduced motion: poster only, no video element. Vitest: the button pauses
   and resumes; reduced motion renders no video.
9. **Build order and slip plan** (decision 27): V5 → V1 (cheap, above the fold) → V2 → V3 → V4.
   If checkpoint 1 (end of Oct 12 IST) is at risk, ask Sourabh before dropping V4's clips (posters
   stay as stills) or V3. Nothing is dropped without his answer.
- Nit applied: the dark illustration treatment is contrast-checked against the dark wash in the
  dark screenshots (pixel sample of the teal strokes), not by eye.

### V9. Decision 45 for the landing (Sourabh, 2026-10-11)
- Containers up to 1280px (`--lp-max: 1280px`) for the bar, hero and every section; the side
  padding is fluid: `--lp-gutter: clamp(16px, 4vw, 64px)`; section rhythm
  `--lp-space: clamp(64px, 8vw, 128px)`; headline sizes via clamp() instead of fixed breakpoints.
- Hero ≥ 1024: a 50/50 grid (copy | Margo + demo); Margo stays beside the sheet's corner inside
  the right half (no longer pushed into the page margin), 200px at ≥ 1280, ~160px at 1024.
- Full-bleed: the teal trust band and the wash bands already are; V3's illustrations row and V4's
  clip grid may run wider than the 1280 text column (up to 1440px) inside their bands.
- Checks: `tools/shots/landing.py` adds 1280 and 1920 (light and dark) to 1440 and 390; axe 0;
  no horizontal scroll; the static hero test still pins index.html to `HeroStatic`.
- Feed/library, profile and reader are the separate **Wide layout** follow-up (BUILD_PLAN), with
  its own plan; it pushes M8-local, and Sourabh is asked before anything in M8/M9 is cut.
- Reviewer nits applied: illustrations are encoded at ~460px and ~920px (2x) wide and clips at
  ~720px wide (each still ≤ 400 KB), so the wider rows stay sharp; BUILD_PLAN acceptance lists
  axe and screenshots at 1280, 1440, 1920 and 390.

## Amendment: decision 46, landing polish (Sourabh, 2026-10-11)

Sourabh reviewed the landing in the browser after V3 (commit 22e111c): the opening is weak and the
page feels loose. Before screenshots (fresh build, same commit): `docs/evidence/landing/d46-before/`.
Same checkpoint 1 (end of Oct 12 IST); built before §C/§B. Dark illustrations re-verified first
(invert filter, white strokes on the dark wash at 390 and 1440; shots in
`docs/evidence/landing/illustrations/`), no change needed.

### P1. Hero opens on the payoff (items 1, 2, 5)
- **Annotator 0.7.0: `inline` card host.** New option `inline?: HTMLElement`. When set, the card
  renders into that element in normal flow at every width (mode `"inline"`: no popover, sidenote,
  bottom sheet or scrim), `open()` doesn't scroll the page, and outside clicks, scroll and Escape
  don't close it (Escape moves focus back to the mark). The close button is hidden; exactly one
  note stays open, and tapping another mark swaps it. Everything else (marks, demo action,
  loadExplanation, scrollable body region) is unchanged; the reader never sets `inline`.
  Vitest: inline renders inside the host with no scrim at a narrow width; open() calls no
  scrollIntoView; outside click / scroll / Escape leave it open; tapping another mark swaps it; axe 0.
- **Open note on load.** `DemoFrame` gets a note slot under the paragraph inside the sheet;
  `MiniDemo` passes it as `inline` and, after each `update()`, opens that persona's **featured
  note**: the first note with an analogy, preferring "bps" (Software engineer → bps, Cricket fan →
  tighter policy because its bps refresher has no analogy, Policy student → bps). The map lives in
  `demoPersonas.ts` (`FEATURED_NOTE`), with a vitest that each featured note exists in demo.json
  and has an analogy. Switching "Read as" swaps the open note. Focus is never moved on load or on
  a persona switch.
- **No empty area.** The sheet's fixed min-height goes; the sheet is as tall as source line +
  paragraph + open note. The note body keeps its own max-height (desktop ~330px, phone ~260px)
  and scrolls inside (already a focusable region), so the hero height stays stable across
  personas. Check: the gap between the note's last visible line and the sheet's bottom edge ≤ 24px
  for all three personas (measured in `tools/shots/landing.py`).
- **First paint.** `HeroStatic` (and so index.html) renders the default persona's featured note
  as plain, inert markup in the slot (`DemoNoteStatic`: domain, term, level line, Background,
  "What the author is saying", from demo.json, styled by landing CSS to the inline card's box:
  same padding, max-height and fonts). The annotator replaces it in the same box. CLS < 0.1
  (Lighthouse) and a measured slot-height difference ≤ 4px between static and live at 1440 and 390.
  The static hero test keeps index.html pinned (`UPDATE_HERO=1`).
- **Margo attached to the note.** `MargoHero` moves from the head row's corner to the note slot:
  absolutely positioned at the open note's top-right edge, arm and hand reaching onto the card's
  top edge (handing it over), ~120px at ≥ 1024, ~88px below. Moods per persona as now. It never
  covers note text (bounding-box check: no intersection with the card's text nodes).
- **Sentence case.** "Read as:" (visible label, sentence case); "From The Economic Times" in
  sentence case; inside `.lp`, card labels (domain, Background, What the author is saying) and
  every other landing label lose `text-transform: uppercase` and letter-spacing (scoped override
  in landing.css; the reader's card styles are untouched). Check: no element on "/" or /privacy
  has computed `text-transform: uppercase` (script, both themes).

### P2. Nav and a higher hero (item 3)
- Bar: wordmark · "How it works" (anchor to `#how-it-works`, the section gets that id) ·
  "Privacy" (client route) · "Sign in" (Google, same handler and busy state as the hero) · a small
  primary "Try the demo" button (same demo handler, current persona) · theme toggle. Below 720px:
  wordmark, "Sign in", "Try the demo", toggle; "How it works" and "Privacy" stay in the footer
  (Privacy already is; "How it works" added). Static first paint: links and buttons present but
  inert until the chunk loads (as the hero CTAs today). 44px targets.
- Spacing: the bar-to-headline gap drops to ~24–40px (clamp); headline clamp max reduced so it
  sits in 2 lines at 1440 ("Read anything. / Understand all of it."). **1440×900 first view:**
  headline, subline, both CTAs and the demo with the open note's title and first lines of
  Background all inside the viewport. **390×844 first view:** headline, CTAs and the open note's
  title plus at least one Background line inside the viewport (mobile hero spacing tightened to
  fit; copy unchanged). Both checked by bounding boxes in the script, screenshots in the log.

### P3. Product shot becomes a phone at the hero card (item 4)
- The laptop frame, desktop shot and the `lp-shot` section are removed (desktop shot files
  deleted from `public/landing/`). The phone frame, smaller (~180px wide at ≥ 1024), sits
  absolutely at the bottom-right of the hero demo card, overlapping its corner, never its text
  (bounding-box check against paragraph and note); hidden below 1024 (`display: none`, so not
  requested: `<picture>` inside a `display:none` subtree still loads, so it is rendered only when
  `matchMedia('(min-width: 1024px)')` matches, via a small hook). Not in the static paint; it
  doesn't affect layout (absolute), so no shift. The caption moves into the demo caption: "A real
  paragraph from The Economic Times and real notes; the words are unchanged. Tap a highlighted
  term."

### P4. Tighter sections (items 6, 7, 9)
- `--lp-space: clamp(56px, 6.5vw, 96px)` (was 64–128). No section with an empty half.
- Problem: on ≥ 1024 the heading and a one-line intro share a row (heading left, intro right,
  baseline-aligned): intro "Three ways a good article loses its reader." (stacked below 1024). The
  italic line becomes a pull quote right under the three cards (larger italic serif, teal rule).
- "What you can read": centred, the four formats as one row of four at ≥ 768 (2×2 below), heading
  centred above.
- Final CTA: two columns at ≥ 1024: left Margo (happy) + title + CTAs; right the knowledge-map
  clip (`Clip` with `clip-map`, same lazy load, pause control and reduced-motion poster). Below
  1024: stacked, centred, clip under the CTAs.

### P5. How it works clips re-cropped (item 8)
- `landing_media.py --clips` re-records the four clips (no product shots) with tight crops: the
  highlighted term and the opening card only (clip-note, clip-simpler: the term's line + the card;
  clip-know: the chip + the term; clip-map: the map's changing region), recorded at
  deviceScaleFactor 2 and encoded at 720px wide so text renders at ≥ ~14 CSS px in the grid
  (checked on the posters at 1440 and 390). Poster = a frame with the card open (for clip-note,
  the last frame after the card has slid in, verified non-blank by a pixel-variance check in the
  script). Same budgets: ≤ 400 KB per file, WebM + MP4, WebP poster; `STEPS` sizes updated.
- **Production writes (this amendment):** ≤ 2 runs of `landing_media.py --clips`, each 1
  anonymous demo reader and its docs, deleted with `DELETE /v1/me`; per run 1 "Know this?" answer,
  ≤ 3 "Knew this", explain hit counters (+N); "Say it simpler" is cached (0 generations; the
  dry run confirms, and the run refuses if not cached). No LLM spend expected.

### P6. Checks and docs
- `tools/shots/landing.py`: first-view boxes at 1440×900 and 390×844, the note-gap check per
  persona, the no-uppercase check, Margo/phone overlap checks, static vs live slot height; axe 0 at
  1920/1440/1280/390 light and dark (card open is now the default state); no horizontal scroll;
  first view at 390×844 < 1.5 MB; landing chunk < 60 KB gzip, main < 150 KB.
- Lighthouse (next step in the log) runs after P1–P5 on the polished page.
- After screenshots: `docs/evidence/landing/d46-after/` (1440×900 and 390×844 folds, full pages,
  each persona's open note, dark). STATUS §10 decision 46; BUILD_PLAN landing section; DESIGN §20.
- Build order: P1 → P2 → P3 → P4 → P5 → checks. If checkpoint 1 is at risk, ask Sourabh before
  dropping P5 (the current clips stay).

### Decision 46 round 1 (plan-reviewer REVISE, 10 items + 2 found while reading the annotator; all applied, these override P1–P6)
1. **1440×900 = the whole demo.** The script requires the entire demo figure (toggle, sheet,
   open note box at its max-height, caption) plus headline, subline and CTAs inside y ≤ 900, for
   all three personas. 390×844 stays: headline, CTAs, note title + one Background line.
2. **390×844 fallback order (mobile only), decided now:** (a) the fine print moves below the
   demo; (b) the CTAs sit side by side (shorter visual width, same labels; if a label wraps, the
   pair stacks again and we go on to c); (c) the note's level line is hidden. Anything beyond that
   goes to Sourabh.
3. **All-caps really gone.** The `.lp` override resets `text-transform: none`, `font-variant:
   normal` and `letter-spacing: normal`, with selectors more specific than the annotator's
   runtime-injected ones (e.g. `.lp .rl-card .rl-card__domain`). Script: on "/" and /privacy, both
   themes, no element has computed `text-transform: uppercase`, a `font-variant` containing
   `small-caps`, or `letter-spacing` > 0.02em.
4. **Inline semantics.** In `inline` mode the card is `role="group"` (same
   aria-labelledby/describedby), no `role="dialog"`/`aria-modal`; the status live region stays
   silent on load and on persona switches (it announces only after a reader-initiated open, as
   today). Vitest: inline has no dialog role.
5. **Persona-switch race.** `MiniDemo` awaits `update()`, keeps a sequence number and opens the
   featured note only if it is still the latest switch; `open(id, { focus: false })` never scrolls
   in inline mode. Vitest: A→B→A toggled fast ends with A's featured note open.
6. **Static → live swap in one frame.** `DemoNoteStatic` stays until the live inline card has
   its explanation rendered (no skeleton visible: the demo explanation is resolved before the card
   is revealed), then the static note is removed and the live card shown in the same frame. The
   static markup includes the demo action button's box and the footer label. The script samples
   the slot height every animation frame from load through the swap (max − min ≤ 4px).
7. **Phone geometry.** The phone overlaps only the card's border/padding corner and hangs outside
   the right and bottom edges; the hero gets bottom padding so it ends above the next section.
   Bounding-box checks: no intersection with paragraph, note body (also after scrolling the note
   body to its end), figcaption, Margo, or the next section's heading. No horizontal scroll at
   1024 and 1280 (smallest right gutter); if the phone + Margo don't fit at 1024, the phone shows
   from 1280 only.
8. **Clip legibility measured.** `landing_media.py` records each crop's CSS width; the landing
   script computes displayed clip width ÷ crop CSS width × 14 px (smallest card body size) and
   requires ≥ 14 at 1440 and ≥ 12 at 390 (single column, phone); numbers logged in
   `docs/evidence/landing/d46-after/clips.txt`.
9. **Removals updated together:** the V6 vitest over `public/landing/` (names and sizes),
   `landing_media.py` loses the desktop product-shot capture (phone shot kept, `--clips` added),
   `lp-shot` styles removed, DESIGN §20 and the V2 caption text updated, `ProductShot.tsx` reduced
   to the phone.
10. **Slip plan.** If checkpoint 1 is at risk, ask Sourabh about dropping, in order: P5 (current
    clips stay), then the final-CTA map clip (centred Margo + CTAs instead). A log line with the
    time after P1 and P2 so the risk call happens early.
11. **No focus trap inline.** The card's Tab cycling (`onCardKeyDown`) is off in inline mode; Tab
    moves through the card and on to the page.
12. **No hover peeks inline.** Hovering another mark doesn't open or schedule a close in inline
    mode (the open note never disappears); click, tap, Enter or Space swaps it; clicking the open
    note's own mark is a no-op.
- Round 2: **APPROVE**. Nits: the 12 px phone clip figure is in STATUS §10's decision 46 row; if
  item 7's fallback (phone from 1280 only) is used, it is logged and added to that row.

## Amendment: decision 46b, hero follow-up (Sourabh, 2026-10-11)

After P1–P5 (commits 4fdfb6e…). Then the landing is frozen and the milestone continues with §C
and §B (onboarding).

### Q1. Left column (items 1, 2)
- `.lp-hero` at ≥ 1024: `align-items: start`; the copy column starts level with the "Read as:" row.
- Under the subline, above the CTAs (in `Hero`, so in `HeroStatic` and index.html too): a list of
  three value lines, each a tiny Margo face (`Margo` 22px; idle, think, happy; aria-hidden) and one
  sentence in sentence case, the exact copy Sourabh gave. Then one small proof line built from
  `evals.json` (real numbers, never rounded): "15/15 misleading notes caught · 24/25 faithful notes
  passed in our tests" (Sourabh's example said 25/25; the data says 24/25, so the line says 24/25),
  linking to the trust band (`#how-we-test`, the id goes on the trust section). evals.json joins the
  main bundle (≈ 0.2 KB). Then the two CTAs and the fine print as now (on phones the fine print
  stays below the demo, round 1 item 2).
- Spacing tuned so at 1440×900 the copy column's bottom is within ~80px of the demo's bottom
  (check: |copy bottom − demo bottom| ≤ 80 at 1440×900 and 1280×800).

### Q2. The open note shows "What the author is saying" in full (item 3)
- The card grows instead of scrolling: the note slot loses its fixed height; the inline card and
  the static note take their natural height (no inner scroll). No Background trimming (it would
  drop the analogy sentence, the point of the demo).
- To keep the whole demo inside 1440×900 for the tallest note (Cricket fan, ≈ +90px), the hero
  sheds height above the note: the source line moves into the caption ("From The Economic Times:
  a real paragraph and real notes; the words are unchanged. Tap a highlighted term."), the demo
  paragraph uses 19px at every width, sheet padding 20px, Margo 88px, hero top padding ≤ 8px,
  caption one line beside the phone. If it still doesn't fit, the order is: Margo's gap above the
  note, then the toggle row's margin; anything beyond goes to Sourabh.
- Static → live: `DemoNoteStatic` mirrors the default note at natural height; the swap check
  (spread ≤ 4px across frames) stays and now guards that the two heights match.
- Checks: the 1440×900 whole-demo check for all three personas; a new check that the card body
  doesn't scroll (scrollHeight ≤ clientHeight + 1) and the author text's last line is inside the
  card, per persona, at 1440, 1280 and 390; the note-gap check stays.

### Q3. Fixes from the first full check run
- axe `scrollable-region-focusable` (serious) on the hero card at ≥ 1280: gone with Q2 (nothing
  scrolls); the annotator also re-runs its overflow check when an inline card is revealed
  (0.7.1), so a scrolling inline body is always focusable (vitest).
- clip-map at 390: 10.4px < 12px. Re-cropped from the encoded clip (ffmpeg crop of the existing
  WebM/MP4/poster to the centre 400 CSS px of the 480; no new recording, no production write);
  `clip_crops.json` → 400.

### Q4. Checks
`tools/shots/landing.py` at 1440×900, 1280×800 and 390×844 (plus the existing widths): all
decision 46 checks, the copy/demo bottom check, axe 0, no horizontal scroll. After screenshots to
`docs/evidence/landing/d46-after/`. Lighthouse after the freeze (log's next step).

### Decision 46b round 1 (plan-reviewer REVISE, 3 items; applied, these override Q1–Q4)
1. **Below 1024 the value lines and proof line render after the demo** (same markup in `Hero`,
   moved by grid order on the phone layout that already uses `display: contents`, so `HeroStatic`
   and index.html are unchanged). The 390×844 first-view check stays as it is; a new check asserts
   the value list's top is below the demo figure's bottom at 390.
2. **What must pass where:**
   - 1440×900: whole demo in view for all three personas; |copy bottom − demo bottom| ≤ 80.
   - 1280×800: headline, subline, CTAs, the open note's title and the "What the author is saying"
     label in view (all three personas); the copy/demo bottom check for the default persona only.
   - 390×844: unchanged (headline, CTAs, note title, one Background line).
   - Every width: no inner scroll and the author text's last line inside the card.
3. **clip-map re-crop keeps what changes.** Before cropping, diff the first and last frames of the
   current encode; every changed pixel (luma difference > 24) must fall inside the 400 CSS px box,
   placed off-centre around the changed region if needed (width unchanged). If the changed region
   is wider than 400 CSS px, the crop stays at 480 and the 390 shortfall goes to Sourabh. The new
   legibility figure goes in `docs/evidence/landing/d46-after/clips.txt`.
- Round 2: **APPROVE**. Nit applied: the proof line's link is the only focusable part of the moved
  block, so below 1024 a second proof line is rendered after the demo in the DOM and the copy-column
  one is `display: none` (not focusable); the value lines (no controls) move by grid order. The
  phone layout's `display: contents` now applies below 1024 (phone-only tweaks stay below 600).

## Amendment: decisions 46c and 46d, last landing changes before the freeze (Sourabh, 2026-10-11)

### R1. Hero (46c)
- **Phone out of the hero** (`HeroPhone`, its CSS and the hero's reserved bottom padding removed;
  `shot-phone.*` files stay unused for now). Sourabh's optional phone frame in "Gloss reads with
  you" is not added (scope; the shot repeats the same note). The landing then shows no product
  shot besides the live demo and the clips.
- **Source line in the card's header**, one line above the paragraph: "From The Economic Times ·
  real paragraph, real notes; the words are unchanged" (sentence case, muted UI text, wraps only
  below 600px). The figcaption under the card goes ("Tap a highlighted term" is dropped; the note
  is already open and the marks are visibly tappable).
- **"Read with Gloss:" row** under the CTAs (≥ 1024 only; mobile unchanged): small chips
  Articles · Any link you paste · YouTube · Podcasts. "With notes" chips carry the reader's teal
  highlight underline and a teal dot; "in your feed" chips are plain; a short legend follows
  ("● with notes · others in your feed"). The chips' accessible names carry the same words
  ("Articles, with notes"). In `Hero` (static paint too). Data shared with the Formats section
  (one `FORMATS` list in `landing/formats.ts`).
- **Height and alignment:** at 1440×900 and 1280×800 the whole hero (default persona: copy column,
  toggle, card) fits in the first view, and |copy column bottom − card bottom| ≤ 40. To get there:
  bar 56px, hero top padding 0, sheet padding 16px, Margo 72px, and the note footer's demo button
  and "Explanation — not the author's words" on one row on the landing (≥ 600px). If 1280×800 still
  doesn't fit, the order is: the note's level line hidden at heights ≤ 820px, then the copy
  column's spacing; beyond that, ask Sourabh. Other personas may run past the fold after a switch
  (user action); their note must still show in full (no inner scroll).
- **Fixes from the last run:** Margo touched the paragraph's last line at 1440 → the note's top
  margin becomes Margo's full overhang (0.62 × width) so Margo never reaches the paragraph
  (bounding-box check stays). Swap spread 69/173px → `DemoNoteStatic` is made to match the live
  card exactly (same footer row, same label sizes, pitch hidden on phones in both); the swap check
  compares the slot height on the last static frame with the first live frame (≤ 4px) and reports
  font-swap reflow separately (CLS is guarded by Lighthouse < 0.1).

### R2. How it works clips (46d)
- **One tile shape:** every tile 16:10 (`aspect-ratio: 16 / 10`, video `object-fit: cover`
  only as a guard: the recordings are 16:10), a true 2×2 grid ≥ 768px with number/title/text rows
  aligned across each row (subgrid); one column below. The staggered layout from P5 goes.
- **Natural zoom, whole lines, never upscaled:** recorded at deviceScaleFactor 2 in a 680px-wide
  viewport (body text 21px, column ≈ 600px, cards float under their term), cropped to 660×412 CSS
  px (16:10) around the full text column, so lines are whole; at the 1440 tile width (≈ 612px)
  body text shows at ≈ 19.5px. Encoded at the crop's native 1320×824; if a clip can't meet 400 KB
  even at the highest CRF tried, it is downscaled (1188, then 1056 wide), never upscaled. A soft
  16px fade at the tile's top and bottom edges (CSS mask) instead of hard cut lines. On phones the
  tile is ≈ 358px wide, so text shows at ≈ 11px: accepted consequence of one natural-zoom
  recording (the earlier 12px phone target no longer applies; told to Sourabh).
- **Each clip shows its step** (live site, one temporary demo reader, deleted with DELETE /v1/me;
  no generations: the precheck must report 0):
  1. "Know this?" → "Not really" → the chip collapses to "Noted, thanks." → (cut: the app shows the
     new highlight on the next load, which is what it does today) the term as a highlight.
  2. A fresh load of the article: the paragraph plain, then the highlights ink in one by one
     (the annotator's stagger); then a second take at 1280px of the margin's "N notes for you" list
     filling (the list only exists ≥ 1200px), cropped to the rail with blank gutter as padding
     (no cut words).
  3. Tap a highlight → the card opens with the Background and its analogy tag → "Say it simpler"
     rewrites it (the cricket fan's "tighter policy": cached one band down).
  4. The knowledge map with 2–3 nodes filling in (before/after the "Knew this" corrections).
- **Posters** are chosen per clip at the frame that shows the action (1: "Noted" with the term;
  2: highlights in; 3: card open with Background; 4: the filled map), checked non-blank; ≤ 400 KB
  per file; reduced motion shows the poster only (unchanged).
- **Production writes:** ≤ 3 runs, each 1 anonymous demo reader and its docs (deleted), 1 "Know
  this?" answer, ≤ 3 "Knew this", explain hit counters +N; 0 generations.

### R3. Checks and freeze (46c/46d C)
- `tools/shots/landing.py` + `landing_d46.py` updated: the 46c fit and ±40 alignment at 1440×900 and
  1280×800 (default persona), notes in full for all personas, values after the demo at 390, no
  caps, Margo overlap, swap, clip tiles 16:10 with equal heights per row, clip text ≈ 18–20px at
  1440 (from the crop width), posters non-blank; axe 0; first view < 1.5 MB.
- Before/after screenshots at 1440×900, 1280×800 and 390×844, light and dark, into
  `docs/evidence/landing/d46-after/` and the log. Commit; the landing is frozen until the tweak
  window; then §C and §B (onboarding).

### 46c/46d round 1 (plan-reviewer REVISE, 3 items; applied, these override R1–R3)
1. **Phone clip legibility (option b, ask first).** ≈ 11px clip text on phones is put to Sourabh as
   a question before the freeze commit; his answer goes in AUTOPILOT_LOG. Until he says yes, R3
   lists "390 clip text ≥ 16px" as failing. If he wants phone versions instead, each `--clips` run
   also records a 390px take from the same temporary reader (same write counts), served below
   768px via `<source media>` with a phone poster, ≤ 400 KB each, checked ≥ 16px at 390.
2. **Lighthouse before the freeze** (moved from Q4 into R3): pinned `lighthouse@12.8.2` against the
   local preview, mobile (390) and desktop (1440), light theme; CLS < 0.1 and mobile LCP < 2.5 s
   are gates; numbers in `docs/evidence/landing/d46-after/lighthouse.txt`. If CLS fails, the static
   note gets the same metric-matched font fallbacks as the live card before the freeze.
3. **Step 1's text says what the clip shows:** "Every note you open, skip or mark “Knew this”, and
   every “Know this?” you answer, updates your map. Say “Not really” and next time that term is
   highlighted for you." `landing_d46.py` checks step 1's rendered text contains "next time".

### 46d product fix (Sourabh, 2026-10-11): no cut around the reload
- Sourabh: "don't cut around the reload. Fix it in the product." After a "Know this?" answer is
  saved (PATCH /v1/me/graph succeeds), the reader refetches the article's annotations and calls
  `annotator.update()` with them, so "Not really" turns the term into a highlight at once and
  "Yes" removes its mark, with the usual staggered ink-in; no page reload. A failed refetch keeps
  the current marks (the answer is already saved; logged, no error shown). Test (web vitest): after
  a successful answer the annotations are refetched and update() receives the new list; a failed
  PATCH refetches nothing. Clip 1 is one continuous take (chip → "Not really" → "Noted, thanks."
  → the term inks in). Step 1's text then needs no "next time" (round 1 item 3 is dropped): "…and
  every “Know this?” you answer, updates your map, right away."
- Sourabh approved the rest of R1–R3 including leaving out the phone frame; his approval of the
  plan as written is taken to include R2's ≈ 11px phone clip text (confirmed with him in the
  report).

### 46d product fix round 1 (plan-reviewer REVISE, 3 items + note; applied, built and tested)
1. **No second chip, and the answered chip stays.** The API leaves the prompt out on
   `refresh=1`; the client also drops any prompt from the refetched list (`withoutPrompts`). The
   annotator (0.7.2) frees an answered prompt's term when the prompt leaves the list (so the new
   span can take it) but keeps its "Noted, thanks." chip until the page goes (cleared on a reader
   change). Vitests (web `knowThisRefresh.test.ts`): a refetch carrying a different prompt renders
   no second chip; the done chip is still there after `update()`; "Not really" inks the term in;
   "Yes" leaves no mark; the article's text is unchanged; save failure → no refresh; refresh
   failure → marks kept, logged.
2. **Not a new page view.** `GET …/annotations?refresh=1` skips `record_view` (weekly trend,
   today's prompt log) and the prompt; API test `test_refresh_after_an_answer_records_no_view_and_
   brings_no_prompt`. It counts once per answer against the annotations rate limit (fine). The
   refetch lives in `ReaderPage` (owner of the annotations) and is passed to `useAnnotator`; the
   web `api.get` has no client cache and the URL differs; an open card stays open if its note is in
   the new list (the annotator only closes leaving ones).
3. **Scoring decides it, so it's tested where it's decided:**
   `test_a_know_this_answer_turns_the_prompt_into_a_span_or_nothing` (tests/test_scorer.py): the
   fixture's prompt concept is not a span before; after the same `correction()` PATCH applies,
   "Not really" makes it a span and "Yes" makes it neither (nor the prompt). The clip relies on the
   live article's "hedging" behaving the same; the recording run checks it.
- Step 1's text: "Every note you open or mark “Knew this”, and every “Know this?” you answer,
  updates your map, right away." ("skip" dropped: per DESIGN §6 a dismissal moves the annotation
  threshold, not the map.)
- 11px phone clip text: Sourabh's words so far are "Everything else in your 46c/46d plan is
  approved, including leaving out the second phone frame." That isn't an explicit answer, so it is
  asked again; until he says yes, "390 clip text ≥ 16px" stays failing in R3.
- Round 2 REVISE (1 item, applied): **the fix ships before clip 1 is recorded.** Order in R3:
  (a) a branch `knowthis-refresh` off `main` carrying the fix (API route + test, scorer test,
  annotator at 0.7.2 — its inline mode and demo-button fix come along; the reader never sets
  `inline` — and web `ReaderPage`, `useAnnotator`, `answers.ts`, `api.ts`, the vitest), PR,
  milestone-reviewer SHIP, green CI, merge; (b) deploy API then web from up-to-date `main`, each
  with Sourabh's yes; (c) live check: one temporary demo reader answers "Not really" and the term
  inks in without a reload (reader deleted; counts within R2's ≤ 3 runs); (d) only then
  `landing_media.py --clips`, and the clips commit is the freeze commit. What the API deploy
  changes for live readers: one extra annotations request per "Know this?" answer (at most three a
  day, DESIGN §6.5); `refresh=1` called arbitrarily only skips the view record and the prompt.

## Amendment: decision 46e, device frames with full-UI captures (Sourabh, 2026-10-11)

Replaces 46d's clip crops (R2 natural-zoom tiles) and settles round 1 item 1: Sourabh: "Answer
to the 11px question: not relevant any more; on phones the framed full-UI shots are pictures of
the product, that's fine." The 46d product fix (PR #25) is merged; the API and web deploys come
first (step 1 needs live "Not really" behaviour), then this, then the freeze and onboarding.

### S1. Frames
- One CSS/SVG device-frame family (no stock images), shared by both sections: a laptop (screen
  bezel, camera dot, hinge base), an external monitor (thin bezel, stand) and a phone (rounded
  body, notch). Screens are 16:10 for laptop and monitor (the 1440×900 captures are 16:10); the
  phone screen is 390:844. One subtle shadow token (`--shadow-float`), light and dark.
- `landing/DeviceFrame.tsx`: `<DeviceFrame kind="laptop|monitor|phone">` wrapping a `<picture>`
  or a `Clip`; frames are decorative, the media carries the alt text.

### S2. "See it in action" (new section right after the hero)
- Desktop (≥ 1024): an external monitor (right, behind) showing the whole Gloss window on the For
  you feed, and a larger laptop (left, front, overlapping the monitor's lower left) showing the
  reader with the "bps" note open as a sidenote. Below 1024: one phone frame showing the reader
  with the bottom-sheet card. Heading "See it in action", a one-line caption (the source credit:
  "Gloss on an Economic Times article; the article's words are unchanged").
- Captures: `landing_media.py --stills` on the live site as the temporary demo reader: 1440×900
  viewport at deviceScaleFactor 2 (2880×1800), light theme, full window (no crop); the phone at
  390×844 DPR 2 (780×1688). Exported AVIF + WebP at 1x (1440 / 390 wide) and 2x (2880 / 780),
  never upscaled; `<picture>` with explicit width/height, lazy (below the fold), `decoding=async`.
  Budget: posters/stills ≤ 120 KB per file at 1x; the 2x files are stills, ≤ 250 KB each (the
  budget Sourabh gave is for posters of loops; stills are listed so the reviewer can hold them).
- The phone frame is rendered only below 1024 and the desktop pair only at ≥ 1024
  (`useMediaQuery`), so each device downloads only its own images.

### S3. How it works: four framed loops
- Each step is a laptop frame (16:10) showing the full reader/profile window at 1440×900, recorded
  at DPR 2 (screencast frames 2880×1800), encoded at native 2880×1800 if within budget, else at
  the 1x 1440×900 (a downscale, never an upscale). Budget: ≤ 600 KB per loop at 2x; posters ≤
  120 KB (WebP); reduced motion = poster only (unchanged).
- Guiding the eye: each clip has a focus box (the action's area as a fraction of the frame, from
  the DOM during recording, stored in `clip_focus.json`); the tile applies a gentle zoom toward it
  with a CSS transform on the video (`scale` ≤ 1.15, `transform-origin` at the box centre) eased
  in after the clip starts and out before it loops, plus a soft radial spotlight overlay (a dimmed
  edge, opacity only). Off under reduced motion. No hard crop: the full window stays in the frame.
- Steps (same content as 46d): (1) "Know this?" → Not really → "Noted, thanks." → the term inks in
  without reload (needs PR #25 live; the run checks it and stops otherwise); (2) a fresh load with
  the highlights inking in while the margin "N notes for you" list fills (1440 has the rail, so one
  take); (3) tap a highlight → card opens with Background and analogy tag → Say it simpler;
  (4) profile knowledge map with 2–3 nodes filling in.
- Grid: 2×2 at ≥ 768 with equal 16:10 tiles and aligned text rows (46d's subgrid stays); one column
  below. Phones: the framed full-UI loop is a picture of the product (small text accepted per
  Sourabh); if autoplay is blocked (`play()` rejects), the poster shows with a centred "Tap to
  play" button (44px, labelled per clip) that starts the loop.
- Production writes: ≤ 3 runs of `landing_media.py --clips --stills`, each 1 temporary demo reader
  and its docs (DELETE /v1/me), 1 "Know this?" answer, ≤ 3 "Knew this", explain hit counters +N;
  0 generations (precheck must report 0).

### S4. Spacing
- `--lp-space: clamp(72px, 9vw, 128px)` (≈ 72px at 390, 128px from ≈ 1420px); the hero gets the
  same bottom padding before "Everyone reads past something"; every section boundary keeps it.
  Check: the gap between consecutive section contents ≥ 72px at 390 and ≥ 120px at 1440.

### S5. Checks and freeze
- `landing_d46.py`: 46d's clip-text check is replaced by: tiles 16:10 with equal heights per row,
  every loop file ≤ 600 KB and poster ≤ 120 KB, stills within S2's budgets, the media query rule
  (phone images not requested ≥ 1024, desktop images not requested at 390), zoom scale ≤ 1.15 and
  none under reduced motion, a "Tap to play" fallback test (vitest with `play()` rejecting),
  section gaps (S4), first view unchanged (< 1.5 MB, no landing media before scroll).
- Lighthouse (round 1 item 2) before the freeze; screenshots at 1440×900, 1280×800, 390×844, light
  and dark, into `docs/evidence/landing/d46-after/`; merge `main` into `landing` first (PR #25).
- Then the landing is frozen; §C and §B (onboarding).

### 46e round 1 (plan-reviewer REVISE, 4 items; applied, these override S1–S5)
1. **The feed capture costs nothing.** The monitor shows the Newcomer demo reader's For you feed
   (the persona of the "bps" note). `landing_media_precheck` and `landing_media.py --dry-run` check
   that this feed is served from the seeded `persona_feeds/newcomer` entry (no feed build), with 0
   searches and 0 generations; the real run refuses otherwise. S3's production-writes line adds
   "0 searches".
2. **One frame family everywhere.** The final CTA shows step 4's loop in the same `DeviceFrame`
   laptop, with the same zoom, pause and poster rules and the same files (no extra download). S5
   adds the removals: 46d's tile media in `public/landing/` replaced by the framed loops, the
   `clip_crops.json` / natural-zoom path in `landing_media.py` and its checks in `landing_d46.py`,
   and any expected names or sizes in the file-size checks.
3. **Pause stops all motion.** The zoom and spotlight run only while the clip plays: the Pause
   button and leaving the viewport stop them and reset the transform (class removed); reduced
   motion never adds them. Vitest: after Pause the tile has no running animation
   (`getAnimations()` empty / zoom class absent), and none under reduced motion.
4. **Where the media checks run, and a slip rule.** The first-view bytes and "no landing media
   before scroll" checks run at 1440×900, 1280×800 and 390×844; at 1920×1080 the section's top may
   be in view, so there the check is only that no media is eager (all `loading="lazy"` / no video
   `src` before near). If checkpoint 1 (end of Oct 12 IST) is at risk, ask Sourabh first about
   dropping the zoom and spotlight (plain framed loops stay), then the monitor (the laptop alone).
