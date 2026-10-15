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
  change (gate in R2).
- `/v2` is linked from nowhere (no nav, footer, README, sitemap), sets
  `<meta name="robots" content="noindex, nofollow">` while mounted, and its title is
  "Gloss · Same content. Your shape." Every button and link that would act (Sign in, Reshape
  something, Reshape an article, Sign in with Google, Try it on any article, Get the extension)
  renders but does nothing: no handler, no auth import, links are inert `<span>`s styled as
  before. Section anchors (How it works, How we test) still scroll; Privacy and the footer's
  outbound links stay as they are (footer "as is").
- Signed-in visitors at `/v2` get the app's normal not-found page (routing for signed-in readers is
  in the main bundle and stays untouched); view it signed out or in a private window.
- First paint on `/v2`: see R12.

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
  their pictures and titles) or replaced by sentences taken word for word from the prompt (steps: "Read, listen, watch, or
  scan." / "Every sentence traces back to the original." / "Every reshaped sentence is checked
  against the original." / "The app remembers the lengths, levels, and formats you pick, so next
  time it starts where you like it."). Images, fonts, colours and spacing unchanged; stills keep their
  truthful alt texts even where the new caption doesn't match them.
- **Reshape demo** (right panel): controls Length (2 min / 5 min / Full), Level (Simple / Standard /
  Expert), Format (Read / Listen / Watch / Scan) with the existing `Segmented`; caption "From The
  Economic Times · reshaped from the original · every line traces to its source"; two columns,
  "Original" (the one public sentence, R4–R7) and "Your shape". **Every shape line is a clause of
  the sentence or runs of its own words** (ellipsis marks a cut; no new words), with a grey tag
  (¶5 s1). Length picks clauses, Level picks full or trimmed forms, Format lays them out (Read: lines; Scan: bullets, trimmed; Listen / Watch: each line with the time it would
  start at 150 words a minute, as a mock). Hover, focus or tap a line highlights its clause in
  Original. Changing a control reflows "Your shape" over 300 ms: lines are keyed by sentence, so
  the same elements move (FLIP); new ones fade in; reduced motion: no animation. No gloss card,
  no word underlines. "Try it on any article" under the demo, inert.

## Tests (first)
- `test/landingV2.test.tsx`: renders every v2 heading and the prompt's key strings; no element has
  an action (buttons have no click handler: the module imports nothing from `lib/auth` or
  `lib/router`'s `navigate`, checked on the source); noindex meta present while mounted and gone
  after unmount; `/` still renders the current page (its headline).
- `shapes.ts`: see R4–R6 (strict in-order runs, protected words, tag).
- Existing landing tests unchanged and passing.

## Checks and acceptance
1. `pnpm -r typecheck`, `pnpm -r test`; the R2 bundle gate.
2. Local preview: `/` before and after screenshots identical at 1440 and 390; `/v2` at 1440 and
   390, light and dark: axe 0 serious/critical, no horizontal scroll; the demo reflows and
   highlights (a short recording to `docs/evidence/landing-v2/`).
3. milestone-reviewer SHIP → PR → CI → merge → `make deploy-web` on Sourabh's yes → live: `/`
   unchanged (same chunk behaviour, headline), `/v2` renders signed out, noindex present.
4. Revert path: delete `landing/v2/` and the two router lines (or revert the PR) and redeploy.

## Round 1 (plan-reviewer REVISE 12; applied, these override the sections above)

**Sourabh's answers (2026-10-15):** concept label: "not needed we will remove /v2 before
submission" (no banner; removing `/v2` is added to the Oct 17 submit row and recorded as decision
63). More article text: "your call" → **no new publisher text**: the demo reshapes only the one
Economic Times sentence already in the repo (`demoParagraph.json`), since removing `/v2` later
would not remove added text from the public history.

**R1. The copy, verbatim:** the teammate's prompt is the Appendix below; the page uses its strings
exactly, and the render test checks them. Where it changes a heading without a body, the plan's
choices above stand (problem cards: picture + new title, old body dropped; How it works bodies:
the prompt's own sentences, listed above).

**R2. Bundle gate:** main's JS byte-identical to `main`'s once chunk file names are normalised,
and ≤ 150.00 KB gzip; `LandingPage`'s code unchanged apart from the router; no new shared chunk
(nothing `landing/v2/` imports moves out of its current chunk; checked in the build manifest).

**R3. Inert, tested.** Source scan of `src/landing/v2/*` only: no import of `lib/auth`, `lib/api`,
any `*Api`, or `navigate`. Behaviour test: `lib/auth` mocked and `fetch` spied; render `/v2`, click
every button and every inert `.btn` span (the live links listed next are left out): no auth
function called, no fetch, path still `/v2`. The only live navigations: the wordmark to `/`, Privacy to `/privacy`, the in-page
anchors, and the footer's links, kept as is (footer wins over the inert list; the in-page "Get the
extension" is inert).

**R4–R6. Shapes:** one sentence, clauses c1–c5, tag `¶5 s1` from the corpus id `p5` (tested); every
line is a clause or runs of its words, in order, non-overlapping, case and punctuation exact; the
protected words ("25 bps", "October", "possible", "according to Bank of America (BofA).") appear
in every Length × Level × Format (tested). No quotes in this sentence, so no quote-balance rule is
needed. Length keeps clauses, Level picks full or trimmed forms, Format lays them out.

**R7.** No new publisher text (above). The caption names The Economic Times (as now).

**R8. Access:** each "Your shape" line is a button with an accessible name including its tag;
focus, hover or click marks its clause in Original (click toggles); the mark is background plus
underline, not colour alone; when the columns stack and the marked clause is off-screen it scrolls
into view (`block: "nearest"`, instant under reduced motion). Tests: focus marks, blur clears,
click toggles; with reduced motion mocked no animation runs; arrow keys move each control.

**R9. CSS scoped:** every selector in `v2.css` starts with `.lp2`; no existing `.lp-*` class is
restyled; a test scans the file.

**R10.** No banner (Sourabh). Decision 63 in STATUS §10 with his quotes; §9 rows: Oct 15 (built,
deployed on his yes) and Oct 17 (remove `/v2` before submitting: delete `landing/v2/` and the
router lines, redeploy, check `/v2` shows the app's not-found or the landing).

**R11. Cut-off and records:** not merged and deployed by end of Oct 15 IST → it stays on the branch,
undeployed, and Oct 16 work is untouched. Deploy: `make check-gcp`, then `make deploy-web` from a
clean, up-to-date `main`. Docs: STATUS §5 bundle line, an acceptance section, AUTOPILOT_LOG.

**R12. First paint:** on `/v2` index.html boots the shell ("Opening Gloss…"), not the static hero;
the router wraps `LandingV2` in its own `<Suspense fallback={null}>`. No old-hero flash.

Nits taken: dark mode checked with emulated `prefers-color-scheme: dark` (the v2 bar keeps the
existing theme toggle, which only changes local appearance); any recording ≤ 3 MB.

## Appendix: the teammate's prompt, verbatim (Sourabh pasted it, 2026-10-15)

```text
some changes 
Edit the existing page at glossreader.web.app. Keep the current layout, sections, fonts, colors, and spacing. Change only the text and the behavior of the right-panel demo described below. Do not add new sections or new visual styles.

TEXT CHANGES, in page order:

Nav: rename "Try the demo" to "Reshape something".

Hero headline: replace "Read anything. Understand all of it." with "Same content. Your shape."

Hero subhead: replace with "Every article, video, podcast, and paper comes in one fixed shape. Reshape it for how you're reading right now. Every sentence traces back to the original."

Primary button: replace "Try it as a demo reader" with "Reshape an article". Keep "Sign in with Google".

Under the buttons, keep the note and change it to: "The demo needs no account, and ending it deletes what it recorded."

Feature points (replace the three current ones):
- "Pick your length." Shorter for a quick read, full for depth. Same source either way.
- "Pick your level." Simpler or more technical, built from the same sentences.
- "Pick your format." Read, listen, watch, or scan. Every version comes from the same source.

Trust line: replace the "misleading notes caught" line with "Every reshaped sentence is checked against the original. [X/Y] reshaped passages traced correctly in our tests." Leave [X/Y] as placeholders until real numbers exist.

"Read with Gloss:" becomes "Works on:". Chips: Articles, Papers, Lectures, Videos, Podcasts, Documentaries, Any link, Chrome extension.

RIGHT PANEL (demo):
- Replace the three persona tabs ("Software engineer", "Cricket fan", "Policy student") with three control groups: Length (2 min / 5 min / Full), Level (Simple / Standard / Expert), Format (Read / Listen / Watch / Scan). Each group shows one selected option.
- Caption above the demo: "From The Economic Times · reshaped from the original · every line traces to its source"
- Show the paragraph in two columns: "Original" and "Your shape." Each line in "Your shape" starts with a small grey source tag (for example ¶2, s1). Hover or tap highlights the matching sentence in "Original."
- Changing a control reflows "Your shape" over about 300ms. The same sentences move; they are not replaced.
- Remove the gloss card (Background, Analogy badges, "What the author is saying") and the "Explanation — not the author's words" footer.
- Remove the underlines on single words ("bps", "tighter policy").
- Button under the demo: "Try it on any article".

SECTION CHANGES:
- "See it in action" caption: "Same Economic Times article, three shapes: full read, 2-minute version, and audio. Each line links back to the original."
- "Gloss in your browser" heading becomes "Reshape in your browser." Body: "Open any page and pick a shape." Keep the install steps.
- "Watch and listen" heading becomes "Videos and podcasts, your shape." Body: "Paste a YouTube video or podcast link. Get the transcript reshaped by length or level, with each line pointing to the moment it came from. Tap any line to play that moment."
- "Everyone reads past something." heading becomes "One shape doesn't fit every reader." Cards: "Too long for this moment", "Too dense for this reader", "Wrong format for this place". Closing line: "Same content. No two readers need it in the same shape."
- "Gloss reads with you." heading becomes "It learns your shapes." Body: "The app remembers the lengths, levels, and formats you pick, so next time it starts where you like it."
- "How it works" steps: "Pick a shape", "Reshape it, sentence by sentence", "Check each line against the source", "Save the shapes you like". Remove "Margo" from the step text.
- Stats row: replace with "[X/Y] reshaped lines traced to source", "[X/Y] changed-meaning lines caught", "[X/Y] shapes kept the original's facts". Use real numbers only.
- "What you can read" list: Articles, Papers, Lectures, Videos, Podcasts, Documentaries.
- Final CTA heading: "Your next piece, in your shape." Button: "Reshape an article".
- Footer: keep as is.

Do not change images, fonts, colors, or spacing.
```

Reading notes: the stats row says "Use real numbers only" but no such numbers exist, and the trust
line says to leave `[X/Y]`; both show `[X/Y]`. "The paragraph in two columns": the original is one
sentence here (R7), so "Your shape" lines are its clauses and hover marks the clause.

## Round 2 (plan-reviewer REVISE 1; applied above)
How it works bodies are now sentences taken word for word from the Appendix (no "reordered"); the
render test checks all four. Stale text above Round 1 folded in. The behaviour test leaves out the
live links. Line buttons carry `aria-pressed` (already in the draft).
