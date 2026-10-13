# Wide layout (decision 45, Sourabh 2026-10-11)

**Read the two review rounds at the end first:** "Round 1" and "Round 2" override the sections
before them. Superseded values still in the body: the reader's `vw` clamps, the 264px / 300px
sidebar tracks, `layout()`'s `{ gap, dot }` option, the first `mapSize` table, the 24px spine
tolerance and acceptance 3's wording. plan-reviewer: REVISE, REVISE, **APPROVE** (2026-10-13).

## Context

Decision 45: pages feel cramped with large side margins on wide screens. The landing already uses
the width (#26). This is the follow-up for the three app pages (BUILD_PLAN "Wide layout"):

- **Feed/library:** container up to ~1280px, wider rows, the sidebar filled; at ≥ 1440px a third
  column ("Your map this week" mini-map and goals).
- **Profile:** domain cards in more columns; the knowledge map spans the full container width and
  is taller.
- **Reader:** the article text column stays ~680px; the note margin on the right as now; at
  ≥ 1280px a slim left rail (contents, reading progress, notes count).
- Fluid spacing with clamp() so 1024, 1440 and 1920 all look intentional; screenshots at 1280,
  1440, 1920 and 390, light and dark; axe 0.

Today: `.feedwrap` and `.topbar__inner` stop at 1240px with rows capped at 720px; the profile
stops at 1100px with every section but the cards and the map capped at 760px, and the map is a
fixed 760×600 viewBox scaled into its box; the reader grid is 680 + 64 + 300 = 1044px centred.

**Web only.** No API, Firestore, prompt, model or annotator-package change. No production write
other than the web deploy. Branch `wide-layout`.

Out of scope: the landing, onboarding, Connect and privacy pages; the extension; anything below
960px except checking nothing regressed (390 shots); section headings in articles (see R1).

## One open interpretation (flagged to Sourabh, not blocking)

**Answered 2026-10-13:** Sourabh said yes to this reading and to the topic tiles (Round 2 item 3).

**R1 "contents" in the reader's left rail.** Articles are stored as flat paragraphs
(`ContentDetail.paragraphs: {id, text}[]`; `app/ingest/extract.py` keeps no headings), so there
are no sections to list. Extracting headings would change ingestion and need the 290-article
corpus and the cached demand profiles re-run: not before the Oct 16 freeze. The rail's "contents"
is therefore a **reading spine**: a vertical track of the whole article with a tick where each of
this reader's notes sits, the part already read filled in. It is derived from positions only; no
article text is repeated or altered. Recorded in STATUS §10 under decision 45.

## Shared tokens (`styles/tokens.css`)

```
--page-max: 1280px;                       /* app pages: top bar, library, profile */
--col-gap: clamp(40px, 4.5vw, 72px);      /* between page columns */
--section-gap: clamp(48px, 5vw, 80px);    /* between page sections */
@media (min-width: 1440px) { :root { --page-max: 1520px; } }
```

`--gutter` stays stepwise (16 / 32 / 48): the reader grid, the annotator's insets and the landing
depend on it. `.topbar__inner`, `.feedwrap` and `.profile__main` all use
`width: min(100% - 2 * var(--gutter), var(--page-max))`, so the logo and the account chip line up
with the page edges on every app page (today the bar is 1240 and the profile 1100).

Final pixel values are tuned on the harness screenshots; the constraints in "Acceptance" are what
must hold.

## A. Feed / library (`styles/library.css`, `components/library/Sidebar.tsx`, new `WeekPanel`)

1. **Container and columns.** `.feedwrap`: `grid-template-columns: minmax(0, 1fr) var(--side-w)`,
   `gap: var(--col-gap)`, `--side-w: clamp(280px, 24vw, 340px)`. At ≥ 1440px:
   `minmax(0, 1fr) 264px 300px` with 48px gaps (the sidebar's two columns, below). Under 960px:
   one column as today.
2. **Wider rows.** `.feedmain` max-width 720 → 820px. Row thumbnail 120×120 →
   `clamp(120px, 11vw, 164px)` wide at 4:3 from 1280px (fixed CSS box, so no layout shift); title
   22px → `clamp(22px, 1.1rem + 0.35vw, 26px)`; lede max 600 → 640px. Under 960px unchanged.
3. **Sidebar, two groups** (`Sidebar.tsx`): the blocks sit in two wrappers,
   `.side__col` A = Read any link, Topics for you; B = Your map this week, Your goals.
   960–1439px: the wrappers stack in one column (A then B): the sidebar is **filled** with the
   map. ≥ 1440px: `.side` becomes a two-column grid, A beside B: B is the **third column**. DOM order equals visual order at every width (A1, A2, B1, B2), so Tab
   order never zig-zags. At ≥ 1440px and `min-height: 760px` each wrapper is
   `position: sticky; top: calc(64px + var(--s8))` (each is two short blocks); not sticky at
   960–1439px, where the single column can be taller than the screen.
   Order change to note: goals now come after topics (today: Read any link, goals, topics).
4. **"Your map this week"** (`components/library/WeekPanel.tsx`, default export, **lazy chunk**):
   - Rendered only when `(min-width: 960px)` matches (`useMediaQuery`), so phones make no extra
     request and load no extra code. The block reserves its height (skeleton, 240px) before the
     chunk and the data arrive.
   - Data: one `profileApi.overview(persona)` (`GET /v1/me/graph?view=overview`, existing,
     deterministic, no model call, ≤ 100 nodes, `general` rate-limit bucket). No second request:
     "this week" comes from the nodes' `rose_this_week`.
   - Pure helpers in new `lib/weekMap.ts`: `miniMapNodes(overview, max = 24)` (nodes that rose
     this week first, then by `weight` desc, then id; only domains that keep a node) and
     `weekLine(nodes)` ("3 ideas moved up this week: A, B and C" / "Nothing moved up yet this
     week"; at most 3 labels, then "and N more").
   - Drawing: `layout()` from `lib/mapLayout.ts` at 300×230 with a new optional
     `{ gap, dot }` (defaults = today's 30 and 1; the mini-map passes 16 and 0.6), topic names
     as cluster labels, this week's risers ringed in `--accent-ink`. The SVG is `role="img"` with
     an `aria-label` ("Your map: N ideas across M topics") and is not interactive; the
     `weekLine` text under it carries the same information; then a link "Open your map" →
     `/profile#kmap-title` (44px target). No animation.
   - States: loading skeleton; empty (no nodes: "Your map fills in as you read."); error ("Your
     map didn't load." in `side__note`, nothing thrown). Demo readers: the heading reads
     "{Persona}'s map this week" and the goals block keeps "Sign in with Google to set reading
     goals".
5. **Topics tab filters**: the topic chips and the Source select already wrap; no change beyond
   the wider column.

## B. Profile (`styles/profile.css`, `pages/ProfilePage.tsx`, `components/profile/KnowledgeMap.tsx`, `lib/mapLayout.ts`)

1. **Container**: `.profile__main` 1100 → `var(--page-max)`; title and summary keep their 760 and
   720px measures.
2. **Domain cards in more columns.** `.dom__grid`:
   `repeat(auto-fit, minmax(min(100%, 220px), 1fr))` (5 across at 1280, 6 at ≥ 1440, cards
   stretch when there are fewer; today 4 fixed). The grid's hairline background shows through
   empty cells of a short last row today; cards draw their own right and bottom hairlines
   instead and the grid background is paper. The 960 and 420px overrides go (auto-fit covers
   them; check 2 across at 390 is still readable, else keep `1fr` under 420px).
3. **Knowledge map, full width and taller.**
   - `lib/mapLayout.ts`: `mapSize(boxWidth) → { width, height }`, pure: under 760 → today's
     760×600 (narrow and stacked layouts unchanged); else width = boxWidth rounded down to 40,
     capped at 1160; height = clamp(600, round(width × 0.66), 760).
   - `layout()` spreads clusters on an **ellipse** instead of a circle: `rx = width × 0.37`,
     `ry = height × 0.33` (today both come from `min(width × 0.37, height × 0.4)`, which would
     leave a 1160px canvas using its middle 600px). The 760×600 layout shifts slightly
     (rx 240 → 281); the existing invariants (deterministic, inside the canvas, labels never
     overlap, You in the middle) must still pass there.
   - `KnowledgeMap.tsx`: a `ResizeObserver` on `.kmap__canvas` feeds `mapSize`; `W`/`H` become
     state; the viewBox equals the measured size, so labels stay 12px instead of scaling. The
     40px rounding means the layout recomputes only at steps, not on every pixel of a resize.
   - CSS: `.kmap__grid` columns `minmax(0, 1fr) clamp(300px, 24vw, 360px)`; the canvas height
     follows the SVG (min-height 520 stays as the floor). Under 960px unchanged (440px canvas,
     inspector below; list view default under 640px).
4. **Sections below the map in pairs.** A wrapper
   `.profile__pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: var(--section-gap) var(--col-gap); }`
   so two sections sit side by side from ~1000px and stack below it, with no media query; a pair
   with one child (demo readers have no Preferences) is one full-width column whose text keeps
   the 760px measure. Pairs, in DOM order = visual order:
   - Goals | This week (**`WeekCard` moves** from after the map to beside Goals, both above the
     map; on a phone the order becomes Goals, This week, Map; DESIGN §15.1 is updated),
   - Analogies | Preferences,
   - Describe yourself | Your data.
   The `:not(.kmap):not(.doms):not(.summary) { max-width: 760px }` rule becomes a rule on the
   pair's children.

## C. Reader (`styles/reader.css`, `pages/ReaderPage.tsx`, new `components/reader/ReadingSpine.tsx`, `lib/spine.ts`)

1. **Unchanged:** `--measure: 680px`; the right margin (`.rail`: "N notes for you", then the open
   card as a sidenote) and everything the annotator measures (`.reader__body`, `.rail`,
   `--rl-top-inset`, `--rl-pmark-left`); the drawer under 1200px.
2. **Left rail at ≥ 1280px.** `.reader__grid` gets `--spine-w: clamp(72px, 7vw, 160px)` and
   `--spine-gap: clamp(56px, 5vw, 96px)`, is widened by `spine-w + spine-gap` and padded on the
   left by the same amount, so the header, action bar, figure and prose all stay in one 680px
   column and the whole grid stays centred. `--rail-gap` becomes `clamp(56px, 5vw, 96px)` and
   `--rail-w` `clamp(300px, 22vw, 360px)` from 1280px (1280: 72 + 56 + 680 + 56 + 300 = 1164 of
   1184 available). The spine is absolutely positioned in `.reader__body` (already
   `position: relative`) at `left: calc(-1 * (var(--spine-w) + var(--spine-gap)))`,
   `top: 0; bottom: 0`, with a sticky inner block at `top: var(--rl-top-inset)`: out of flow, so
   the two-column body grid the annotator measures is untouched and nothing shifts when it
   mounts. Paragraph markers (`--rl-pmark-left: -48px`) stay inside the 56px+ gap.
3. **`ReadingSpine`** (default export, **lazy chunk**, loaded only when `(min-width: 1280px)`
   matches and the article is ready):
   - `<aside aria-label="Your place in this article">`: the notes count ("9 notes", tnum; hidden
     until notes resolve, "No notes" never shown: the line is just absent), "6 min left" /
     "Finished", and the track.
   - Track: 2px hairline, height `min(56vh, 480px)`; the read part is an accent line scaled
     with `transform: scaleY()` written directly from a rAF-throttled scroll handler (the
     pattern `ProgressBar` uses; no re-render per frame). "N min left" is React state that only
     changes when the whole-minute value changes. No `aria-live`.
   - Ticks: one short dash per note at its position in the article; solid for "new", outlined
     for "refresher" (the margin list's vocabulary). The tick of the hovered or open note is
     emphasised (`handle.hovered` / `handle.active`, already passed to the rail). Ticks are
     decorative (`aria-hidden`), not focusable and not clickable: the margin list and the marks
     are the controls.
   - The top progress line stays (it is the only progress cue under 1280px).
4. **Pure helpers** (`lib/spine.ts`): `spineTicks(annotations, paragraphs) → {id, at, level}[]`
   (`at` in 0..1 = characters before the note's anchor start, counting whole earlier paragraphs,
   over total characters; sorted; an unknown `paragraph_id` is skipped) and
   `minutesLeft(wordCount, progress)`. `readingProgress(top, height, viewport)` moves out of
   `ProgressBar` into `lib/spine.ts` and both use it (same numbers as today).
5. **Up next grid** (`.upnext__grid`) and the recap stay in the 680px column.

## Bundle budget (main ≤ 150.00 KB gzip; today 148.08)

`LibraryPage`, `Sidebar` and `ReaderPage` are in the main bundle; the profile is already lazy.
`WeekPanel` (+ `lib/weekMap.ts`) and `ReadingSpine` are lazy chunks; `mapLayout` is shared by the
profile and `WeekPanel` chunks. Expected main-bundle cost: two `lazy()` imports, two media
queries, the sidebar wrappers and `lib/spine.ts`'s `readingProgress` ≈ 0.5 KB. Measured with
`pnpm --filter web build` before the first change and at the end, same way as STATUS §22. If main
passes 150.00: move `Sidebar`'s goals block into the `WeekPanel` chunk first. CSS total recorded
before and after (no CSS budget is close: app CSS is under 20 KB gzip).

## Files

- `apps/web/src/styles/tokens.css`, `library.css`, `profile.css`, `reader.css`
- `apps/web/src/components/library/Sidebar.tsx`, new `WeekPanel.tsx`
- `apps/web/src/components/profile/KnowledgeMap.tsx`, `apps/web/src/pages/ProfilePage.tsx`
- `apps/web/src/pages/ReaderPage.tsx`, new `components/reader/ReadingSpine.tsx`,
  `components/ProgressBar.tsx`
- `apps/web/src/lib/mapLayout.ts`, new `lib/weekMap.ts`, `lib/spine.ts`
- `apps/web/test/mapLayout.test.ts`, new `weekMap.test.ts`, `spine.test.ts`,
  `wideLayout.test.tsx`
- new `tools/shots/wide.py`
- Docs (below)

## Tests (offline: vitest + jsdom, no network)

Written first for the pure helpers (red, then green):
- `mapLayout`: at 1160×760 with 6 topics and 60 nodes: deterministic, every node inside the
  canvas, labels never overlap, cluster centres span ≥ 60% of the width; at 760×600 the existing
  invariants still pass; `mapSize`: 759 → 760×600, 864 → 840×600, 1004 → 1000×660,
  2000 → 1160×760; `{ gap, dot }` defaults reproduce today's output for a fixed input.
- `weekMap`: risers first and never dropped before non-risers, cap of 24, stable order on ties,
  domains without a kept node removed; `weekLine` for 0, 1, 3 and 5 risers.
- `spine`: tick positions for notes in the first, a middle and the last paragraph; sorted;
  unknown paragraph skipped; `level` defaults to "new"; `minutesLeft` rounds up and reads 0 at
  the end; `readingProgress` matches the old `ProgressBar` numbers on 4 fixed cases.
- `wideLayout.test.tsx` (matchMedia mocked): under 960px `Sidebar` renders no map block and
  `profileApi.overview` is never called; at 1280 the block order is Read any link, Topics, Your
  map this week, Your goals; overview failure shows "Your map didn't load." and the rest of the
  sidebar still renders; a demo persona gets "{Persona}'s map this week".
- `pnpm -r typecheck`, the existing web (71), annotator and extension suites stay green.

## Harness (`tools/shots/wide.py`, emulators only)

Pages: library (For you, Topics), profile (overview, one topic, list view, inspector open),
reader (margin list, an open sidenote, the end block). Sizes 1024, 1280, 1440, 1920 and 390, light
and dark, for one demo persona; the profile and library again for one emulator Google reader with
a goal (third column with goals). Per page and size: screenshot into `docs/evidence/wide/`, axe at
every impact level, horizontal-scroll check, the "no text under 13px" check, and these asserted
with `eval` (the script exits non-zero on any failure):

1. Library: page content width ≥ 1150 at 1280 and ≥ 1300 at 1440; row width between 600 and
   840 at 1024, 1280, 1440 and 1920; the two sidebar groups share a column at 1280 and sit side
   by side at 1440 and 1920; the map block exists at ≥ 1024 and not at 390; top bar edges equal
   the page container's edges (± 1px) on library and profile.
2. Profile: ≥ 5 card columns at 1280 when there are ≥ 5 cards, and no empty grey cell; map
   canvas ≥ 820 wide and ≥ 600 tall at 1280, ≥ 1100 wide and ≥ 720 tall at 1920; a map label's
   computed font size is 12px at every desktop size; Goals and This week side by side at 1280,
   stacked at 390; arrow keys still move between map nodes and Enter opens the inspector.
3. Reader: prose column 680 ± 1px at 1024, 1280, 1440 and 1920; spine present at ≥ 1280, absent
   at 1024 and 390; spine and paragraph-marker rectangles never intersect; an open note card's
   rectangle lies inside the right rail's at 1280, 1440 and 1920 (the annotator still places
   sidenotes correctly); the spine's fill grows after scrolling to the end and the text reads
   "Finished"; tick count equals the notes count.
4. Layout shift: summed `layout-shift` entries < 0.1 on the library and the reader at 1440 from
   load until the lazy chunks have rendered.
5. Keyboard: Tab through the 1440 sidebar visits Read any link, topics, the map link, goals in
   that order.

Spend: opening one sidenote per size may generate explanations that aren't cached in the
emulator: ≤ 6 explain + verify calls, < $0.05, counted against the local `LLM_DAILY_BUDGET_USD`.
No search calls, no production access.

Design check on the shots against `rules/web/design-quality.md` and `docs/design/mockup.html`:
hierarchy, rhythm of the gaps, both themes, nothing that reads as an empty column at 1280, 1440
or 1920.

## Acceptance

1. Every harness assertion above passes on the final commit; axe 0 at 1024, 1280, 1440, 1920
   and 390, light and dark, on the three pages; no horizontal scroll.
2. Screenshots at 1280, 1440, 1920 and 390 (light and dark) of library, profile and reader are in
   `docs/evidence/wide/` and referenced from STATUS.
3. The article text is byte-for-byte what it was (the prose column's `textContent` equals the
   API's paragraphs joined, checked in the harness) and the column is 680px.
4. Main bundle ≤ 150.00 KB gzip; the two new chunks' sizes recorded.
5. Under 960px nothing changed except the documented profile order (390 shots compared with the
   Design pass shots).
6. Tests: all suites green; counts recorded.

## Production writes, deploy and spend

- None to Firestore or Cloud Storage. No API deploy (no API change).
- After merge and green CI: `make deploy-web` from an up-to-date `main` (Sourabh's yes).
- Live check after the deploy: the anonymous demo at 1440 (library, reader, profile), read-only;
  Sourabh looks at the three pages on his own screen. The one new production request is
  `GET /v1/me/graph?view=overview` per library visit at ≥ 960px (a read; no model call).

## Schedule and cut order

Plan and review Oct 12 (late). Build and harness Oct 13. milestone-reviewer, PR, merge and web
deploy Oct 13–14. **Checkpoint end of Oct 14 IST:** not merged → ask Sourabh what to cut
(decision 27); M9 stays Oct 15 and the freeze Oct 16. If the build is behind at midday Oct 14,
cut in this order and say so in STATUS: (1) the mini-map drawing (the block keeps its heading,
the `weekLine` text and the link), (2) the reader spine, (3) the profile pairs. Not cut:
containers and wider rows, card columns, the full-width taller map.

## Docs

DESIGN §19 (Library, Reader, Profile bullets), §15.1 (order: This week beside Goals; map sizing);
BUILD_PLAN "Wide layout" (the reading-spine reading of "contents", acceptance); STATUS §1 row,
§4 (R1 as a deviation from decision 45's wording), §5 bundle row, §9, §10 (decision 45 note), a
new §23 acceptance table; AUTOPILOT_LOG; README screenshots are refreshed on Oct 16 as planned.

## Round 1 (plan-reviewer REVISE, 13 items + 3 nits; all applied, these override the sections above)

1. **Reader widths are anchored at 1280** (the `vw` clamps above overflow there: 1197.6 of 1184).
   `--spine-w: clamp(72px, calc(72px + (100vw - 1280px) * 0.14), 160px)`; `--spine-gap` and
   `--rail-gap`: `clamp(56px, calc(56px + (100vw - 1280px) * 0.0625), 96px)`; `--rail-w`
   `clamp(300px, 22vw, 360px)`. Grid: 1164 at 1280, 1223 at 1440, 1392 at 1920. Harness at 1280:
   grid width + 15 ≤ `clientWidth` − 2 × gutter, so a classic scrollbar still leaves 680px.
2. **Sidenote check and width.** `railColumn` (`hooks/useAnnotator.ts`) sizes the card as
   `min(360, viewport − rail.left − 16)`, not the rail's width: with the new geometry the card
   is 342px at 1280 and 360px from 1440 (C.1's "unchanged" excepts this). `railColumn` uses
   `documentElement.clientWidth` instead of `innerWidth` for that subtraction so the 16px edge
   holds with a classic scrollbar (the 1200px threshold keeps `innerWidth`, as media queries
   do); the file joins Files. Harness check: card left = rail left ± 1, card right ≤
   `clientWidth` − 16, card and `.prose` rectangles don't intersect (1280, 1440, 1920).
3. **One coordinate system for the spine.** Fill, "N min left" and "Finished" are measured
   against `articleRef` (`.prose`), the same span the ticks are positions in; the top line keeps
   `pageRef`. `spineTicks` gets `marked` (the resolved notes), so its count equals the margin's
   "N notes for you". Harness: the spine's count equals the rail heading's count; with a mark
   scrolled to mid-viewport the fill's end is within 24px of that note's tick.
4. **`spineTicks` offsets.** `Anchor.start` is an article-level offset over paragraphs joined by
   `"\n\n"`, so `at = anchor.start / joinedLength` (text lengths plus 2 per separator). When
   `start` is missing: the paragraph's start plus `indexOf(anchor.exact)` (the paragraph's start
   when not found). The test fixture is cut from a real annotations response.
5. **Rows are never narrower than today.** ≥ 1440px tracks:
   `minmax(0, 1fr) clamp(232px, 16vw, 288px) clamp(280px, 19.5vw, 340px)`, 40px between columns
   with the hairline centred in each gap (`.side`'s own 40px left padding goes at ≥ 1440). Feed
   column: 819 at 1280, 751 at 1440, 812 at 1920 (cap 820), 634 at 1024. Thumbnail: 132px wide
   (4:3) from 1280, `clamp(132px, 8.25vw, 160px)`, so it only grows past 1600. Harness check 1
   becomes: row ≥ 720 at 1280, 1440 and 1920 and ≥ 600 at 1024; row minus thumbnail and gap
   ≥ 560 at 1440.
6. **The map really is taller.** `mapSize`: under 760 → 760×600; else width = box width rounded
   down to 40, capped at 1160; height = clamp(680, round(width × 0.75), 780). Table: 759 →
   760×600, 877 → 840×680, 998 → 960×720, 1160 and 2000 → 1160×780 (today ≈ 630 tall). The SVG
   is rendered at exactly that pixel size, centred in the canvas (not `width: 100%`). Harness:
   canvas height ≥ 680 at 1280 and ≥ 720 at 1440; `svg.getScreenCTM().a` = 1 ± 0.02 at 1280,
   1440 and 1920 (replaces the vacuous "label is 12px"). At 1024 the box is 658px, under 760:
   the 760×600 canvas scaled to 0.87, exactly as today.
7. **`layout()` is byte-identical for width ≤ 760.** The ellipse (`rx = width × 0.37`,
   `ry = height × 0.4 × 0.82`) applies only above 760; a snapshot test of today's coordinates
   (760×560 and 760×600, fixed input) is committed before the change. Wide tests use the demo
   personas' real shape, 4 topics × 16 nodes at 840×680 and 960×720, plus 6 × 10 at 1160×780,
   with a new invariant: no two dots overlap after clamping (if it fails, clamping moves inside
   the collision passes on the wide path only). Domain cards: auto-fit applies from 961px; the
   960 (2 across) and 420px (1 across) rules stay, so tablets and phones don't change.
   Acceptance 5 reads: "At 390 nothing changed except the documented profile order, compared
   with the before run (item 10)."
8. **The mini-map has its own small placement; `layout()`'s signature is untouched** (its
   constants are for 760×600: at 300×230 the clamps leave 188×106 and the You disc fills it).
   `lib/weekMap.ts`: `miniMapNodes(overview, perTopic = 8, max = 24)` and
   `clusterDots(count) → {x, y, r}[]` (a fixed 96×64 box, phyllotaxis, deterministic). The
   panel is a grid of topic tiles (`repeat(auto-fill, minmax(112px, 1fr))`: 2 across in a 240px
   sidebar, 2 in the 280px third column): each tile is one 96×64 SVG cluster at its natural
   size (never scaled; filled by band, this week's risers ringed) with the topic name and
   "+N this week" under it **in HTML at ≥ 13px**. One `role="img"` label per tile ("Finance: 8
   ideas, 2 moved up this week"). Unit tests: 24 nodes over 6 topics (the overview's
   `MAX_DOMAINS`) keep ≤ 8 per topic with risers first; for 1–8 dots every dot is inside the
   box and no two overlap.
9. **"Open your map" keeps the demo persona:**
   `withParams(new URL("/profile", origin), { persona: personaParam(persona) })` plus
   `#kmap-title`; asserted for a non-default persona in `wideLayout.test.tsx`.
10. **Harness.** (a) The text-size check is written in `wide.py` and scoped to the new elements
    (`.side`, the week panel, the spine): nothing under 13px. (b) The emulator Google reader is
    seeded with 6 chosen topics, so the "≥ 5 card columns" check runs. (c) **Before run:** the
    script is written first with a `--before` mode that records shots and metrics (row width,
    map height, card columns) without asserting, and is run on the branch before any web change
    into `docs/evidence/wide/before/`. (d) Sizes and themes change in place (viewport and
    `data-theme`), never by reloading per size, and any 429 fails the run.
11. **Nothing is cut automatically** (BUILD_PLAN; decisions 27 and 45). If the build is behind
    at midday Oct 14: the profile pairs and the `WeekCard` move are not in decision 45 and are
    dropped first, noted in STATUS. The mini-map drawing and the reader spine are decision-45
    items: stop and ask Sourabh before cutting either.
12. **Recording.** The first commit on the branch, before any code: R1 in STATUS §4 and §10 and
    AUTOPILOT_LOG; two more §4 rows (`--page-max` 1520 at ≥ 1440 against "~1280px"; This week
    above the map against DESIGN §15.1's order). All three repeated in the PR body.
13. **Bundle.** The fallback if main passes 150.00 is a separate lazy **goals** chunk that loads
    at every width (not folded into the week panel, which never loads under 960px).
    `readingProgress` lives in its own module (`lib/readingProgress.ts`), so `ProgressBar` does
    not pull `spineTicks` and `minutesLeft` into main.

Nits, applied: the sticky sidebar columns need `min-height: 900px` (not 760), and the harness
asserts each column's bottom is inside the viewport at 1440×900; `KnowledgeMap` guards
`ResizeObserver` (jsdom has none) and takes its first measurement in a layout effect, so the map
never paints at 760×600 and then jumps; harness spend is ≤ 6 cold cards ≈ $0.054, under $0.06.

## Round 2 (plan-reviewer REVISE, 3 items + 2 nits; all applied, these override everything above)

1. **The spine has its own progress function.** `readingProgress` on `.prose` runs up to half a
   screen behind the ticks. `lib/spine.ts` adds
   `placeInArticle(top, height, viewport, atPageEnd)` = clamp((viewport / 2 − top) / height, 0, 1),
   and 1 when `atPageEnd` (without an end block the prose bottom never passes mid-viewport, so
   "Finished" would never show). The fill, "N min left" and "Finished" use it;
   `readingProgress` (`lib/readingProgress.ts`) is for the top line only. Harness: with a mark
   at mid-viewport the fill's end is within **10% of the track height** of that note's tick
   (ticks are character shares, the fill a pixel share). `spine.test.ts` adds: before the
   article, a mid point, the end, and `atPageEnd` on a short article.
2. **Acceptance 3, reworded** (a "Know this?" chip is a `data-rl-ui` span with its own text
   inside the paragraph): for each `p[data-rl-paragraph]`, the text of a clone with its
   `[data-rl-ui]` descendants removed equals that paragraph's text from the API; and the column
   is 680px.
3. **The tile grid is a second reading of Sourabh's words** ("mini-map"): no "You" centre, no
   edges, one cluster per topic. Recorded as a fourth STATUS §4 row, in the AUTOPILOT_LOG entry
   and in the PR body, next to R1. `weekLine` and its test stay: one line under the tiles ("3
   ideas moved up this week: A, B and C" / "Nothing moved up yet this week").

Nits, applied: the new STATUS §4 rows carry the third cell ("Keep"); the emulator Google reader
is seeded with **three** goals as well as six topics, so the sticky-column check covers the
tallest column (six tiles and three goals against the 804px available at 1440×900). Map box
widths are 874.8 at 1280 and 996.4 at 1440 (the grid's 1px borders): same sizes, 840×680 and
960×720; at 1920 the box is 1158, so 1120×780.
