# Landing v2 concept at /v2 (2026-10-15)

Sourabh, 2026-10-15: a teammate's landing feedback ("Same content. Your shape.": reshape any
piece by length, level and format, every line tracing to the original). Asked whether it fits, I
said it describes features Gloss doesn't have and conflicts with the rule that the author's text
is never rewritten. Sourabh: "lets create /v2 with no link but view only things i belive i need to
do some discussion with teammate on it make according to whatever the prompt is asking", then
"keep sign in and all but as no functionality behind". So: a **view-only concept page** for that
discussion. The live landing at `/` is not changed. Branch `landing-v2` from `main` (846ff01).

## Ground rules
- `/` stays byte-for-byte the same page (same components, same copy); the main bundle does not
  change (gate: main gzip equal to `main`'s, 149.93 KB; the landing chunk may grow by a lazy
  import only).
- `/v2` is linked from nowhere (no nav, footer, README, sitemap), sets
  `<meta name="robots" content="noindex, nofollow">` while mounted, and its title is
  "Gloss · Same content. Your shape." Every button and link that would act (Sign in, Reshape
  something, Reshape an article, Sign in with Google, Try it on any article, Get the extension)
  renders but does nothing: no handler, no auth import, links are inert `<span>`s styled as
  before. Section anchors (How it works, How we test) still scroll; Privacy and the footer's
  outbound links stay as they are (footer "as is").
- Signed-in visitors at `/v2` get the app's normal not-found page (routing for signed-in readers is
  in the main bundle and stays untouched); view it signed out or in a private window.
- On `/v2` the static first paint is skipped (it is for `/` only), so the current hero can flash
  while the chunk loads. Accepted for a discussion page.

## Build
- `pages/LandingPage.tsx`: the default export becomes a two-line router: `/v2` → lazily loaded
  `landing/v2/LandingV2.tsx`; anything else → the existing page, unchanged.
- `landing/v2/` (new, self-contained; deleting the folder and the two lines removes v2):
  `LandingV2.tsx` (bar, hero and every section with the v2 copy, reusing `DeviceFrame`, `Still`,
  `Clip`, `ProblemArt`, `MargoHero`, `Margo`, `Segmented`, `Footer` and `landing.css` classes),
  `ReshapeDemo.tsx`, `shapes.ts`, `v2.css` (only the demo's two columns, tags, highlight and
  motion, using existing tokens).
- **Copy:** exactly the prompt's, section by section (nav, headline, subhead, primary button, fine
  print, the three feature points with the existing Margo faces, the trust line with `[X/Y]`,
  "Works on:" chips, See it in action caption, Reshape in your browser, Videos and podcasts your
  shape, One shape doesn't fit every reader, It learns your shapes, How it works titles, stats row
  with `[X/Y]`, What you can read list, final CTA). Where the prompt changes a heading but gives
  no body (problem cards, How it works steps), the old body is dropped (problem cards keep
  their pictures and titles) or replaced by the prompt's own sentences (steps: "Choose a length,
  a level and a format." / "The same sentences, chosen and reordered for your shape." / "Every
  reshaped sentence is checked against the original." / "The app remembers the lengths, levels,
  and formats you pick."). Images, fonts, colours and spacing unchanged; stills keep their
  truthful alt texts even where the new caption doesn't match them.
- **Reshape demo** (right panel): controls Length (2 min / 5 min / Full), Level (Simple / Standard /
  Expert), Format (Read / Listen / Watch / Scan) with the existing `Segmented`; caption "From The
  Economic Times · reshaped from the original · every line traces to its source"; two columns,
  "Original" (four real consecutive paragraphs of the demo article, six sentences, from
  `data/corpus_paragraphs.json`, content `2332418841…`) and "Your shape". **Every shape line is the
  original sentence or a trimmed run of its own words** (ellipsis marks a cut; no new words), with
  a grey tag (¶2 s1). Length picks sentences, Level picks full or trimmed versions, Format lays
  them out (Read: lines; Scan: bullets, trimmed; Listen / Watch: each line with the time it would
  start at 150 words a minute, as a mock). Hover, focus or tap a line highlights its sentence in
  Original. Changing a control reflows "Your shape" over 300 ms: lines are keyed by sentence, so
  the same elements move (FLIP); new ones fade in; reduced motion: no animation. No gloss card,
  no word underlines. "Try it on any article" under the demo, inert.

## Tests (first)
- `test/landingV2.test.tsx`: renders every v2 heading and the prompt's key strings; no element has
  an action (buttons have no click handler: the module imports nothing from `lib/auth` or
  `lib/router`'s `navigate`, checked on the source); noindex meta present while mounted and gone
  after unmount; `/` still renders the current page (its headline).
- `shapes.ts`: for every Length × Level × Format, each line's source exists and its text, with
  ellipses removed, is found word for word in that source sentence; Full + Expert + Read is all
  six sentences in order; lines are unique per shape.
- Existing landing tests unchanged and passing.

## Checks and acceptance
1. `pnpm -r typecheck`, `pnpm -r test`; main gzip unchanged (149.93 KB); landing chunk grows only
   by the lazy import.
2. Local preview: `/` before and after screenshots identical at 1440 and 390; `/v2` at 1440 and
   390, light and dark: axe 0 serious/critical, no horizontal scroll; the demo reflows and
   highlights (a short recording to `docs/evidence/landing-v2/`).
3. milestone-reviewer SHIP → PR → CI → merge → `make deploy-web` on Sourabh's yes → live: `/`
   unchanged (same chunk behaviour, headline), `/v2` renders signed out, noindex present.
4. Revert path: delete `landing/v2/` and the two router lines (or revert the PR) and redeploy.
