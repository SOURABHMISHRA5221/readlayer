# Design pass — Gloss (decisions 39, 40)

## Context

M7.5 is merged and live (#20, #21), a day ahead of the Oct 12 checkpoint. BUILD_PLAN's Design
pass (items 1–10, all required) turns ReadLayer into **Gloss**: a Medium-style reading product
that matches `docs/design/mockup.html` (Feed, Reader, Profile and map, Logo and Margo; light and
dark). The mockup is a target, not code to copy: we rebuild it in our components with real data,
accessibility (axe 0, keyboard, 44px targets), the bundle budget, two-phase loading and the
annotation rules intact.

**Out of scope (recorded, not cut):** the mockup's video/podcast rows say "Gloss reads the
transcript and adds notes as it plays"; that is illustrative content, not a BUILD_PLAN item, so
feed videos and podcasts keep opening the original. The extension icon uses the Margo mark, but
the extension lives on the paused `m8` branch, so the icon file is added here and wired in M8.
The deck is M9/Oct 16 work.

## Order, dates and checkpoint

Today is Oct 11 (IST). Design pass runs Oct 11–13; M8-local Oct 14, M9 Oct 15, freeze Oct 16.

1. **Stage 1 (Oct 11):** tokens and fonts, Margo, the Gloss name, the top bar. API A1, A2.
2. **Stage 2 (Oct 11–12):** library as a feed (tabs For you · Topics · Saved, rows, sidebar).
   API A6 (Saved).
3. **Stage 3 (Oct 12):** reader (column, action bar, "Before you read" path, two highlight
   styles, margin contents and level-aligned card, bottom sheet, simpler/deeper, recap). API A3,
   A4. Annotator margin mode.
4. **Stage 4 (Oct 12–13):** profile (summary, domain cards, knowledge map overview in SVG,
   inspector). API A5.
5. **Stage 5 (Oct 13):** sign-in, welcome and account pages on the new tokens; screenshots,
   axe, keyboard and reduced-motion passes; reviews; merge and deploy.

**Checkpoint 1, end of Oct 12 IST:** if stages 1–3 aren't done on the branch, stop and ask
Sourabh what to cut (candidates to name, not to cut: the Saved tab, "Say it simpler / Go
deeper", the recap's undo, the map inspector's evidence list).
**Checkpoint 2, midday Oct 13 IST:** if stage 4 isn't done, ask again, so reviews, merge and
deploy still fit Oct 13. Nothing is cut without his answer.

**Before screenshots:** taken from the live site before any branch change (done 2026-10-11:
`docs/evidence/design/before/`, sign-in, library, For you, reader, profile at 1440 and 390,
light and dark; JPEG, desktop downscaled to 960px wide).

## A. API (apps/api) — small, deterministic, no LLM in any scoring path

1. **Span level.** `AnnotationOut` gains `band` and `level: "new" | "refresher"` computed with
   `explain.inputs.concept_band` (the uncapped band the explanation is written for, not the
   span's capped `demand_p`), so the highlight, the card and the recap agree. new = unaware or
   heard of; refresher = understands or can explain. Pure, no I/O.
   - **Measurement first (offline, no LLM):** the share of refresher spans across the corpus ×
     3 personas at balanced density (span score is (1 − p) × salience against a 0.45 cut, so a
     refresher needs p ≤ 0.55 and salience ≥ 0.9). Reported in the PR and STATUS.
   - If both styles don't appear on the demo article for at least one persona at "For me", stop
     and ask Sourabh how to split the styles; the split is not changed silently.
   - Tests: both levels from fixed states; level uses `concept_band`, not `demand_p`.
2. **Pre-read path.** `preread_path` today keeps only prerequisites with p < `PREREAD_KNOWN`
   (0.7) and already ends at the article's key concept (`steps[-1]`, `PrereadOut.concept_id`).
   Change: prepend the prerequisite where the walk stopped (the first one with p ≥
   `PREREAD_KNOWN`; ties: highest p, then concept id), as a ticked step; `PrereadStepOut` gains `known: bool` = p ≥
   `PREREAD_KNOWN`. No extra last step (it would duplicate the key concept). Still ≤
   `PREREAD_MAX_STEPS` unknown steps plus one ticked step. Tests; DESIGN §6.4 updated.
   The new path UI is rendered by the **web app** (React). The annotator's `renderPreread`
   (used by the extension) skips steps with `known: true` (B7), so it never asks a reader to
   meet a concept they already know.
**One "known":** for the map and the ready rule, a concept is known when the reader's current
p_know (edge with forgetting, else the prior) is ≥ `KNOWN_P` = 0.5 (`reader/goals.py`'s
`is_known`, DESIGN §18), so a prior-only concept can count as known; "known" on the pre-read
path keeps the walk's own `PREREAD_KNOWN` = 0.7.

3. **Say it simpler / Go deeper.** `POST /v1/explain` accepts `shift: -1 | 0 | 1` (default 0).
   The Background is generated for the reader's band moved one step (clamped to the four bands)
   through the **normal verified path** and cached by band, exactly as today's Background cache
   key (`span_hash, band, frame, style`); the shared restatement is reused unchanged. Counts once
   against the explain caps like any request. The response adds `can_simpler` and `can_deeper`.
   Span mode only: `shift ≠ 0` with `paragraph_id` is 422. Shifted Backgrounds are fetched only
   on click, never prefetched. The card's level meter and pitch line use the response's `band`
   (the band the Background was written for). Tests: band clamp, cache key carries the shifted
   band, restatement reused, cap counted once, paragraph 422, a rejected shifted Background
   falls back to the definition as today.
   - **Demo warm-up (Oct 16 seeding):** `warm_demo --shifts` also warms the ±1-band Backgrounds
     of the same top spans (≤ 2 per span, clamped at the ends): ≤ 48 Background entries for the
     3 demo articles × 3 personas × 3 spans, ≈ $0.20 (background generation + background judge
     ≈ $0.004 each), dry run first, recorded in STATUS §9. A cold card is p95 31 s, so the video
     must not show a cold "Say it simpler".
4. **Recap bands.** `POST /v1/me/bands {concept_ids: [≤ 50]}` → `{concept_id: band}` from the
   reader's current state (edge with forgetting, else the prior). Pure read, demo personas
   included (their persona graph). The web calls it **when annotations load** for the span and
   prompt concepts (the snapshot) and again at the end of the article, after flushing the event
   batch (`lib/events.ts`), and diffs the two. Both use `concept_band`, so zero interactions
   give an empty recap (test). Test: bands move after a correction.
5. **Map overview.** `GET /v1/me/graph?view=overview` → for each domain the reader has an edge
   in or interest ≥ 0.5 in (most interest first, ≤ 6 domains): up to 12 **solid** concepts and up
   to 4 **ready to learn** rings, plus prerequisite edges among them and up to 6 cross-domain
   edges. ≤ 100 nodes.
   - Every node's `band` is the reader's current band (edge with forgetting, else the prior,
     the same `concept_band` as A1). **Solid** = band ≥ heard of (by band, then `doc_freq`), so a
     reader with no edges but a high prior in a domain gets solid nodes there: the map shows what
     Gloss thinks they know, as the page title says.
   - **Ready to learn** = not known and every prerequisite known, where known = p ≥ `KNOWN_P`
     (above); by `doc_freq`.
   - Node: `{id, label, domain, band, ready, goal, weight, definition, recent,
     rose_this_week}`: `weight` is `doc_freq` normalised per domain; `recent` is ≤ 3 evidence
     entries `{type, at}` from the edge (empty for prior-only nodes); `rose_this_week` from
     `band_changed_at` / `band_prev` (DESIGN §15.2).
   - **Never empty:** when no domain qualifies (no edges, no interest ≥ 0.5), the reader's
     top-interest domains (the four business domains if none) are used with the same rules, so
     the map shows their prior-based solid nodes and rings.
   - Learning-goal targets are flagged (`goal: true`). Pure over the graph and state.
   - Clicking a domain still loads the existing `?domain=` subgraph (≤ 60 nodes, with search)
     and the `?goal=` goal view stays (the video line uses it); both render in the new SVG layout.
   - Tests: new reader non-empty; a no-edges reader with a high θ gets solid nodes; caps; ready
     rule; goal flag; `rose_this_week`.
6. **Saved.** `users/{uid}/saved/{content_id}` `{at}`, in `USER_SUBCOLLECTIONS` (export and
   delete, test). `PUT` and `DELETE /v1/me/saved/{content_id}` (corpus or own-ingested ids only,
   ≤ 500), `GET /v1/me/saved` → library summaries newest first, through the same per-request
   visibility filter as the library. Signed-in readers need consent; demo readers may save
   (session data under their uid, deleted with it). **Only rows with a `content_id` show Save:**
   corpus and already-opened pages; web-only feed items don't (saving bare URLs would be new user
   data and is not in scope).
7. **Article "Helpful"** (BUILD_PLAN item 3's action bar). New event type `article_helpful`
   `{content_id}` through `POST /v1/events`: stored with the other events (90-day TTL), applies
   no evidence and no θ change, counted per day for M9's evals. Idempotent by event id like the
   rest. Tests: accepted, no knows/θ change, blocked before consent.

DESIGN gets §8 route rows, §6.4 (ticked known steps), §7 (shift), §9 (annotator margin mode,
sheet, highlight levels, `article_helpful`), §15 and §15.1 (overview map in SVG replacing the
Cytoscape/dagre text, domain cards keeping interest), §16/§17 (Saved, library tabs) and a new
§19 "Gloss UI" (name, tokens, Margo rules, highlight levels).

## B. Annotator (packages/annotator, 0.1.0 → 0.2.0) — shared with the M8 extension

Everything new is **opt-in**; with no new options the extension's behaviour is unchanged. The
`ANNOTATOR_VERSION` export stays (`apps/extension/src/background.ts` imports it). Margin and
sheet logic go in new modules (`margin.ts`, `sheet.ts`); `card.ts` (519 lines) only gains the
content changes.

1. **Highlight levels.** Span marks get `rl-mark--new` (soft fill + underline + a small dot) or
   `rl-mark--refresher` (thin underline), from `level`; a missing `level` (an older API) means
   "new". Prompt marks unchanged. Shape cues besides colour: the dot on new, underline weight.
2. **Margin mode.** New option `cardHost?: { container: HTMLElement; align(mark): number }`. When
   given, the card renders inside the host container at the mark's line with a dashed connector;
   without it, today's floating card (the extension's default) is unchanged. **Only with
   `cardHost`** (or an explicit `sheetBelow: 960`), below that width the card is a bottom sheet
   (`role="dialog"`, `aria-modal="false"`, `aria-labelledby` the term, focus moved in, Escape
   and a close button return focus to the mark, max-height 72vh, scrollable).
3. **Card content.** Term, pitch line with a 4-step level meter ("New to you, so this note starts
   from zero" / "You've heard of this, so it skips the basics" / "You understand this, so it's a
   one-line refresher"), "Builds on" (prerequisite labels), Background (analogy tag), "Say it
   simpler" / "Go deeper" buttons when the host provides `loadShifted(item, shift)`, "What the
   author is saying" set as a quote, actions Helpful / Knew this / This is wrong.
4. **Notes list hook.** `onItems(items)` lets the host render "N notes for you" and open a note by
   id (`annotator.open(id)` scrolls the mark into view and opens its card).
5. Paragraph markers only where the API returned a paragraph note (desktop and mobile).
6. Motion: card slide and connector only without `prefers-reduced-motion`.
7. **Pre-read card:** `renderPreread` skips `known: true` steps (A2); vitest case.
Tests (vitest + jsdom): level classes and the "new" default, margin host placement callback,
bottom sheet focus, Escape and labelling, floating mode unchanged without options (including a
narrow window), `open(id)`, axe on the card in both modes; `pnpm --filter extension build`.

## C. Web (apps/web)

1. **Tokens and type** (`styles/tokens.css`, `fonts.css`, `index.html`): the mockup's palette
   (white / #121212, ink, one teal accent, wash, line) in light and dark; Schibsted Grotesk for UI
   and headlines, Source Serif 4 for reading (Google Fonts, `display=swap`, two families,
   fallback metrics updated); article body 21px (19px under 600px); no reader-facing text under
   13px, nothing a reader needs in light grey.
2. **Margo** (`components/Margo.tsx`): the mockup's `margo()` SVG as a component with moods idle,
   think, happy, oops and the 16px mark; `aria-hidden`; optional blink (idle only, off under
   reduced motion, never while the reader page is scrolled into the article). `public/favicon.svg`
   and `public/margo-mark-128.png` (extension icon, wired in M8).
3. **Gloss name** (display only): wordmark, `<title>`s, meta description and og tags, copy on
   sign-in, welcome, consent and empty states, README heading and intro. Firebase project, URLs,
   repo name, ids, localStorage keys and API names stay.
4. **Top bar**: Margo + "gloss" logo, search (library search), "Read any link" (opens the
   sidebar field on desktop, a sheet on mobile), the **demo persona chip** for demo readers (the
   core of the demo: kept, in the keyboard path and the screenshots), theme toggle, account; all
   targets ≥ 44px (fixes the 40px controls noted in STATUS §5).
5. **Library as a feed** (`pages/LibraryPage.tsx` + `FeedPage.tsx` merged into one page with
   tabs): **For you** (feed rows: source and favicon initial, "in Topic · format", bold title,
   one-line serif subtitle, `why` line, read/watch/listen time, "N ideas new to you" tag, goal
   tag, save and "show less like this" icon buttons, thumbnail right), **Topics** (the corpus
   library as rows with topic chips), **Saved**. Right sidebar ≥ 960px: Read any link, Your goals
   (signed-in; demo readers see "Sign in to set goals"), Topics for you chips. URL keeps the tab
   (`/?tab=topics`, `/for-you` stays as an alias). Client-side tab switches (no reload). The For
   you and Saved tab bodies stay **lazy chunks** (main is 138.7 KB of 150 KB today); main-bundle
   size recorded before and after. The stale tagline is replaced with copy for Gloss on any
   subject. Save shows only on rows with a `content_id` (A6).
6. **Reader**: 680px column with kicker (topic), 44px title, serif dek, byline, sticky action bar
   (notes density Fewer / For me / More = minimal / balanced / guided, **Helpful** (A7, with a
   visible "Thanks" state), save, copy link, open original), reading progress bar, "Before you read" path (ticked known steps, the key idea
   last; a step toggles its definition or links to the explainer article), highlight levels,
   right margin with Margo (idle) and "N notes for you" until a note opens, then the card level
   with its line; "Preparing your notes…" with Margo (think) during two-phase loading; the recap
   **"What this article changed"** (Margo happy): concepts whose band changed since the page
   loaded (from A4), each with Undo (the existing correction route in the opposite direction),
   "Not really" answers listed as next on the path, and two Up next items that teach those
   concepts (Up next items whose triggers include them). Undo applies the opposite correction
   (strong evidence), so the row then shows the resulting band, not necessarily the original
   one. If no Up next item teaches them, the recap shows Up next's top two under a neutral label
   ("Read next"), never "teaches X". Up next follows.
7. **Profile**: a readable summary lede (template over domains and frames, deterministic),
   domain cards (level word, ideas known, **interest**, "+N this week" from `/me/profile`'s
   `week.moved_up` grouped by domain, 5-step scale), the map: an **SVG
   radial layout clustered by domain** around "You" (deterministic positions, light collision
   pass), known nodes filled by band, ready nodes as outline rings, goal targets dashed, size by
   weight, an overview of all domains first and a click on a domain label to focus it, new nodes
   (band rose this week) animate in once (none under reduced motion), an inspector panel (term,
   domain and band, definition, "Why we think so" from the edge's recent evidence types and dates,
   I know this / I don't). **Keyboard:** the SVG is `role="group"` with a label and one Tab stop
   (roving tabindex; arrow keys move between nodes, Enter opens the inspector); each node's
   `aria-label` is "label, band[, ready to learn][, in a goal]"; shape cues besides colour
   (rings for ready, dashes for goals, a ring for can explain). The **list view stays**.
   Cytoscape and dagre are removed (−155 KB lazy chunk).
8. **Sign-in, welcome, account** pages re-skinned on the new tokens (no flow changes).
9. **Margo in empty and error states** (oops mood) with what to do next: the empty Saved tab, a
   link that couldn't be opened (Read any link and "Read here" errors), the reader's
   notes-unavailable notice, the app error boundary and the not-found page; happy in the recap;
   think while notes load.

## Data rights, privacy, cost

- New user data: `saved` only (export and delete). Nothing else per user.
- No new LLM inputs: shifted explanations use the same prompt variables with a different band.
- Explain caps unchanged; a shift request counts like any explain request.
- Logs carry `uid_hash` only.

## Tests (offline)

- pytest: A1–A7 as listed (incl. the refresher-share measurement as a script, and "zero
  interactions → empty recap"); `USER_SUBCOLLECTIONS` guard covers `saved`; the annotate route stays
  LLM-free (existing guard).
- vitest: annotator B1–B6; web: Margo moods render aria-hidden, library tab ↔ URL, recap diff
  (pure helper), map layout is deterministic and keeps labels from overlapping (pure helper).
- `pnpm -r typecheck`, `pnpm --filter extension build`, `uv run ruff check .`,
  `uv run pytest -q`, web build with the main bundle < 150 KB gzip.

## Acceptance (run, not assumed)

1. Before/after screenshots at 1440 and 390, light and dark, for library, reader (closed card,
   open card, bottom sheet), profile and map, sign-in; in `docs/AUTOPILOT_LOG.md` (paths) and
   `docs/evidence/design/`.
2. axe 0 serious or critical on every page above; keyboard path: top bar → tabs → a row's
   actions; reader: Tab to a highlight, Enter opens the card, Escape returns focus; map node
   focus and Enter opens the inspector. No horizontal scroll at 390. Targets ≥ 44px.
3. Reduced motion: no card slide, no map pop, no Margo blink.
3b. Non-text contrast, measured in both themes (axe doesn't check it): ≥ 3:1 against the page
    for the refresher underline, the new-highlight underline and fill edge, the ready rings and
    the goal dashes. Values recorded.
3c. Both highlight styles appear on the demo article for at least one persona at "For me" (A1);
    else Sourabh decides.
4. Harness flows: a demo reader opens a note in the margin; "Say it simpler" returns a verified
   Background at a lower band; the recap lists a band change after "Knew this", and Undo applies
   the opposite correction with the row showing the resulting band; a page with no interactions
   shows no band changes; the action bar's Helpful records one `article_helpful` event; Saved
   tab lists a saved article and export contains it; a new Google reader's map is not empty;
   the persona chip switches personas.
5. Two-phase "Open here" and annotation behaviour unchanged (existing tests plus one harness
   open).
6. Bundle: main < 150 KB gzip (before 138.7 KB, after recorded); no Cytoscape chunk.

## Production data writes

None beyond normal use. Live check after deploy: one demo reader saves one article, presses
Helpful once and asks "Say it simpler" once (≈ $0.01), deleted after. No prompt version changes,
so no re-warm now. Later, at the Oct 16 seeding (not in this milestone): `warm_demo --shifts`,
≤ 48 Background entries, ≈ $0.20, dry run first.

## Ship

PR "Design pass: Gloss …", milestone-reviewer SHIP, merge on green CI, deploy API then web (each
with Sourabh's yes), live check, STATUS (§1, §4 deviations, §5, new acceptance section; §9 with
the Oct 11–13 dates, the revised video line with "Say it simpler" and the recap, the
`warm_demo --shifts` step for Oct 16, and the m8 rebase), DESIGN, AUTOPILOT_LOG with
before/after screenshot paths.
**m8 rebase:** `m8` also changes `app/scoring/scorer.py`, `app/content/router.py` and
`test_scorer.py`; right after this merge, rebase `m8` onto main (time reserved at the start of
Oct 14).

## Critical files

API: `app/content/router.py`, `app/scoring/scorer.py`, `app/explain/{router,service,inputs}.py`,
`app/me/router.py`, new `app/me/saved.py`, `app/store/reader_repo.py`, `app/reader/overview.py`
(new, pure), `app/reader/events.py`, `scripts/warm_demo.py`. Annotator:
`packages/annotator/src/{card,mark,ui,styles,index,types,preread}.ts` plus new
`margin.ts`, `sheet.ts`. Web:
`styles/*`, `index.html`, `components/{Margo,TopBar,FeedRow,Sidebar,NotesMargin,Recap}.tsx`,
`pages/{LibraryPage,ReaderPage,ProfilePage,SignInPage,WelcomePage}.tsx`,
`components/profile/{KnowledgeMap,DomainCards}.tsx`, `hooks/useAnnotator.ts`.
