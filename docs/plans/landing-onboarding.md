# Landing and onboarding (decision 41)

## Context

The Design pass (Gloss) is merged and live (#22–#24). Decision 41 (BUILD_PLAN "Landing and
onboarding", all required) adds, before M8: a landing page at "/" for signed-out visitors that
explains problem, failure of existing options, solution and trust in under 30 seconds with a live
mini-demo; and onboarding in 2 screens that visibly uses the web to understand the reader,
replacing consent → field → interests → comfort → frames → liked articles → 8 calibration taps.
The privacy rule stays absolute: free text is never sent to search or to an LLM as-is and is
never stored.

**Open product question (asked 2026-10-11, pending Sourabh):** the live graph (5,206 concepts) has
no concept for "F1", "Formula One", "startups" or "Indian politics" (exact lookup and
`resolve_names` both miss, checked live). Under C as written, the BUILD_PLAN example adds nothing
and shows "Didn't recognise: F1, startups". Proposed addition: a piece that matches no concept is
mapped to the nearest **taxonomy topic** by embedding similarity to the 14 topic scope lines
(no LLM; a threshold; the query is then the taxonomy label, as today), e.g. F1 → Sports, startups →
Business. Built only if Sourabh says yes (then decision 42 in STATUS §10 and BUILD_PLAN C, test
(b) and the DESIGN free-text sentence extended to the topic step, and a labelled set of 20–30
phrases with expected topic or "none" committed before choosing the threshold, precision reported
in the PR per decision 26); otherwise C stays as written. Work starts now: the resolve response
reserves `topics: []` so screen 1 and its tests don't change either way.

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
