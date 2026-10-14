# Landing refresh (decision 61, 2026-10-14)

Sourabh: "we have added lot of new features extention support and all since we last updated our
landing page … can we work on updating it next?" Agreed list (his "list sounds good lets go"):
lead with **the Chrome extension**, **videos and podcasts opening in Gloss**, and **the For you
feed with readiness lines**; everything else on the landing stays. The landing has been frozen
since decision 47; this decision reopens it for these changes only. Branch `landing-refresh` from
`main` after readiness (#37) merges. Built Oct 15, before the Oct 16 freeze.

## Why now
The landing is wrong today: the hero chips and "What you can read" say YouTube and podcasts are
"in your feed" only (`landing/formats.ts`), but since decision 54 short ones open in Gloss with a
transcript and notes. The extension (M8, `extension-v0.8.1`) and readiness (decision 60) are not
mentioned at all.

## What changes

**A. Formats, honest (`landing/formats.ts`, one list for hero chips and "What you can read").**
- Articles, Any link you paste: with notes (unchanged).
- YouTube videos: with notes, up to 10 minutes; longer ones open on YouTube.
- Podcast episodes (Apple Podcasts): with notes, up to 12 minutes; longer ones open where they play.
- Any page in Chrome: with notes, through the extension.
- The caps in the copy come from one constant pair in `formats.ts` (10, 12), with a test that they
  equal the API's `media_max_video_s` / podcast cap in `app/config.py` (read from the file, as the
  eval-numbers test reads its JSON), so copy and server can't drift.
- Hero chips (in `HeroStatic`, so in the **main bundle** and in `index.html`): every chip now gets
  notes, so the dot legend "with notes · others in your feed" goes; chip texts become "Articles",
  "Any link", "Short videos", "Podcasts", "Chrome extension". `index.html` regenerated with
  `UPDATE_HERO=1` (the existing sync test). **Gate: main ≤ 150.00 KB gzip.** If over, the chips
  keep their current four texts (only the false legend is removed and the two `how` values
  change), and the new formats are said only in the lazy sections.

**B. "Gloss in your browser" (new section, landing lazy chunk, after See it in action).**
- A laptop frame with a still of the production extension on a real public page with notes
  marked and one note open, plus the popup ("Read this page"). Alt text says what it shows.
- Copy (each claim checked against the code): nothing runs until you press "Read this page", and
  only on that tab (activeTab); emails, phone numbers, card, Aadhaar and PAN numbers are removed on
  your device before the text is sent (`extension/src/redact.ts`); Gloss won't read mail, banking,
  sign-in or private pages, or any page with a password or card field (`refuse.ts`).
- Install in three steps: download the zip from GitHub Releases, turn on Developer mode in
  chrome://extensions, Load unpacked. Link `${REPO_URL}/releases/latest`. It works for visitors
  once the repo is public (Oct 17, after gitleaks); until then it 404s for anyone but Sourabh,
  as the existing GitHub links do (same open question in `landing/links.ts`).
- Not claimed: Chrome Web Store, other browsers.

**C. "Watch and listen" (new section, lazy chunk, after Gloss in your browser).**
- A laptop still of a short video open in Gloss: player, transcript with time buttons, a note open
  on a transcript term. Copy: short YouTube videos and podcast episodes open with a transcript and
  the same notes; the transcript is made automatically and can contain errors (the reader already
  says so); longer ones open where they play.

**D. See it in action: the feed still re-recorded** (`shot-feed`, monitor frame) so it shows the
readiness lines and "Open in Gloss" on short videos; alt text names the readiness line. The reader
and phone stills stay.

**E. Footer (lazy chunk):** a "Get the extension" link (same releases URL). Nav unchanged (main
bundle).

**F. Step 4 of How it works** ("Your map grows") body gains one clause: For you then tells you
which picks you're ready for. Clip unchanged.

Not changed: hero headline, values, demo, problem, solution, trust band, eval numbers, the four
clips, onboarding, the app.

## Captures (production, read and one demo reader)
- `tools/shots/landing_media.py` gains `--only shot-feed,shot-media` (stills only); `shot-media`
  opens a short video already in the library as the demo reader (the Fireship or Economist video
  from §24, notes already cached) and opens one transcript note.
- `tools/shots/landing_extension.py` (from `m8_live.py`): the production-built extension 0.8.1 on
  the live site as one demo reader, on a page whose fetch doc already exists (m8_live's default
  Wikipedia "Term structure of interest rates" → "Yield curve" corpus doc), opens one note and
  shoots the window and the popup; composes nothing (two stills side by side in the frame).
- **Precheck first** (`scripts/landing_media_precheck.py` extended, read only): prints the exact
  writes and refuses if anything would generate an explanation, search or build a feed beyond the
  counts below.
- **Production writes, at most:** 2 anonymous demo readers (one per script), each deleted at the
  end with DELETE /v1/me (Auth user and `users/{uid}` gone, confirmed in the log); their
  `rec_signals` docs go with them; 0 new `contents/` docs; ≤ 2 explanation generations
  (≈ $0.01) only if the precheck shows a needed note isn't cached, else 0. No search calls.
- Stills: AVIF + WebP at 1x and 2x, through the existing `Still` (lazy, explicit size, not in the
  first view); each ≤ 150 KB at 1x WebP.

## Budgets and checks
- Main bundle ≤ 150.00 KB gzip (measured before/after; A's gate). Landing chunk JS < 60 KB gzip
  (decision 41; now 7.68 KB). First view at 1440×900 and 390×844 unchanged apart from the chips
  (before/after shots); nothing new loads in the first view (network log: no new still fetched
  before scroll).
- axe 0 at every impact, no horizontal scroll at 320, 390, 768, 1024, 1440, 1920, light and dark
  (light default, decision 44). Headings in order; every still has alt text.
- Mobile LCP measured with the same method as decision 47 and reported against the current value
  (the 2.5 s gate was already missed and accepted; this change must not make it worse by > 5%).

## Tests (first)
- `formats.ts`: no entry says "In your feed"; caps equal the API config; the extension entry exists.
- `landingHero.test.ts` sync (index.html regenerated).
- A landing render test: the two new sections render with their headings, the releases link
  (`/releases/latest`, `target="_blank"`, `rel="noreferrer"`), the three privacy claims and the
  three install steps; the footer link.
- Harness `tools/shots/landing_refresh.py` (local build, `vite preview`, no network beyond the
  page's own assets): the audits above, full-page shots at each width and theme into
  `docs/evidence/landing-refresh/`, before (from `main`) and after.

## Acceptance
1. Suites (`pnpm -r typecheck`, `pnpm -r test`; API untouched apart from the config-read test,
   which lives on the web side); budgets above met.
2. Captures done within the production-write counts, demo readers deleted (log lines).
3. Harness: axe 0, no horizontal scroll, first view unchanged, before/after shots.
4. milestone-reviewer SHIP → PR → CI → merge → `make check-gcp` → `make deploy-web` from clean
   `main` (Sourabh's yes) → live: the landing at 1440 and 390 shows the new sections, the stills
   load, axe 0 on the live page.

## Docs
STATUS decision 61, §1 row, §9 Oct 15 row, an acceptance section; DESIGN's landing section (the two
new sections and formats); README's feature list mentions nothing new here (README refresh is
Oct 16); AUTOPILOT_LOG.

## Schedule and cuts
Oct 15, after readiness is live. Checkpoint shared with readiness: **not merged by end of Oct 15
IST → ask Sourabh what to cut** (decision 27). Cut order if time runs short: F, then the re-recorded
feed still (D), then the extension still (B keeps its copy and steps, with the popup still from
`docs/evidence/m8/popup-google-bbc.png` re-encoded), never A (the current page is wrong).

## Round 1 (plan-reviewer REVISE, 8 items; applied, these override the sections above)

**R1. Split the formats list.** `landing/formats.ts` keeps only the hero's chip list (label and
with-notes flag), imported by `HeroStatic` (main bundle). The full list (what, how, caps, the
extension entry) moves to `landing/formatsFull.ts`, imported only by the landing chunk. A test
asserts the chip list is a projection of the full list (same order, same keys). Gate: **main ≤
150.00 KB gzip measured with the split in place**; if over, the chips keep their current four
texts and only the false legend goes (bytes measured both ways).

**R2. Caps from production config.** The web test reads `apps/api/deploy.env.yaml`
(`MEDIA_MAX_VIDEO_S: "600"`, `MEDIA_MAX_AUDIO_S: "720"`) and asserts 600/60 = 10 and 720/60 = 12
against the full list's caps; it also checks `app/config.py`'s defaults (`media_max_video_s`,
`media_max_audio_s`) agree.

**R3. Install steps as the README and the 0.8.1 release say (README "Install the extension
locally").** (1) Download `gloss-extension.zip` and unzip it. (2) In chrome://extensions turn on
Developer mode, Load unpacked, pick the folder. (3) In Gloss: account menu → "Use Gloss on any
site" → Connect (a demo session works). (4) Open a news article, click Gloss, "Read this page".
The render test checks these four steps.

**R4. No overclaim.** The format entry is "News pages in Chrome" (chip "Chrome extension"). The
access line reuses the README's words: "no access to any site until you click it"; it never reads
mail, banking, sign-in or private pages, or a page with a password or card field; emails, phone,
card, Aadhaar and PAN numbers are removed on your device before the text is sent.

**R5. Readiness precondition.** Met: readiness merged (#37) and live (API 00030, web deployed,
live-checked 2026-10-14, STATUS §29) before any capture.

**R6. The feed still shows no known-wrong line.** `shot-feed`: newcomer, light, 1440×900, top of
For you (the first three rows, as the live shot `docs/evidence/readiness/live-foryou-1440-light.png`:
"Ready for you", "A stretch: read up on Income distribution first", and the third row's title only).
The script logs every `.row__why` inside the viewport; acceptance: none of "Economic stocks and
flows", "Supply and demand" (on the AI-guardrails interview) or any other line Sourabh or the
review marks wrong is visible; if one is, scroll or crop so it isn't, else don't keep the still.
The Oct 16 re-seed may change the lines; the still is not re-shot after the freeze.

**R7. One recording, named notes, a complete precheck.**
- Recording: the Fireship video "Every app on Earth is now open source…" (YouTube `wajoP_5Cpw8`,
  356 s), production doc `93053af2e368625142213283d9abe557` (stored, `needs_growth` unset). T05 is
  not stored in production, so it is not used. Opened by the demo reader through Read any link
  (`POST /v1/recs/open`): a stored recording returns early in `media/service.py` `open_media`
  (no slot, no lookup, no transcript, no budget check); the open records `ingested` under
  `users/{uid}`, deleted with the reader.
- Notes opened (each must be cached and verified, both parts, or the precheck lists it as a
  generation): media still: (newcomer, `c_intellectual_property_rights`, 0) on the Fireship doc;
  extension still: (newcomer, `c_yield_curve`, 0) on the Yield curve doc.
- Extension page: m8_live's default Wikipedia "Term structure of interest rates", which redirects
  to "Yield curve"; the precheck asserts `url_hash(<final Yield curve URL>)` is a stored doc (the
  first branch of `ingest/submitted.py` `reusable`), so **0 `ext:` docs, 0 ingest-counter
  increments**; and `needs_growth` is false on both docs, so **0 `graph_growth/` docs** and no
  `/grow` spend. The precheck refuses to proceed if any of these fails.
- `landing_extension.py` keeps from `m8_live.py` only: load the built extension, demo sign-in,
  Connect, open the page, Read this page, open one note, the window and popup shots, DELETE
  /v1/me. Dropped: the forced token refresh, the negative read, the library check.
- **Production writes, at most:** 2 anonymous demo readers with their `users/{uid}` (incl.
  `ingested`, `rec_signals`), all deleted by DELETE /v1/me and confirmed read-only (Auth user and
  `users/{uid}` gone, as `readiness_live.py` does); 0 `contents/`, 0 `ext:`, 0 `graph_growth/`, 0
  ingest-counter increments; ≤ 2 explanation generations (≈ $0.01) only if the precheck lists them;
  0 searches.

**R8. A pinned release link.** The section and the footer link
`${REPO_URL}/releases/tag/extension-v0.8.1`; the render test expects that href.
