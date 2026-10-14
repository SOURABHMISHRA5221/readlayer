# Media follow-up: the YouTube player domain, and a choice in the feed (2026-10-14)

Web only. No API, Firestore, prompt, model or annotator change. Branch `media-followup` from
`main` at 5844e98 (Media merged as #32, API revision 00027 and web live).

## Context
1. **Live, Sourabh's first video in Gloss (Fireship, 5:56):** transcript and notes worked; the
   player showed YouTube's "Sign in to confirm you're not a bot". Tested on 2026-10-14 from this
   network: a local page embedding The Economist video (T05) in an iframe, as Gloss does.
   - Headless Chrome, signed out: **both** `youtube-nocookie.com` and `youtube.com` embeds show
     the bot check (YouTube distrusts the network for anonymous viewers).
   - Sourabh's Chrome, signed in to YouTube: the **no-cookie embed shows the bot check, the
     `youtube.com` embed plays.** The no-cookie domain can't see the viewer's YouTube session.
2. **Sourabh:** feed videos should offer opening in Gloss *or* on YouTube; "keep long ones as
   YouTube only". Today a feed row is one link: Gloss when `open_here` (a known length ≤ 10 min;
   podcasts ≤ 12), else the original. No choice is shown.

## A. Player on `www.youtube.com`
- `lib/media.ts`: `YOUTUBE_ORIGIN = "https://www.youtube.com"`; `embedUrl` unchanged otherwise
  (`enablejsapi`, `origin`, `rel=0`, `autoplay`, `start`). The message check stays strict
  (`event.origin === YOUTUBE_ORIGIN` and `event.source === player`); seek and play go to that
  origin only.
- Still click to load (R10): until the reader presses play there is no iframe, only the
  thumbnail from `i.ytimg.com` with `referrerPolicy="no-referrer"`. The iframe keeps
  `referrerpolicy="strict-origin"` and its `allow` list.
- Privacy page, video section: the player loads only when you press play, from YouTube; if you
  are signed in to YouTube in this browser, YouTube can link the view to your account, as with
  any embedded video. (Replaces "from YouTube's no-cookie domain".)
- Signed-out viewers on a network YouTube distrusts still get the check; nothing on our side
  changes that. "Open on YouTube" stays under the player. Stated in STATUS §5.
- DESIGN §21.4 and STATUS §4 (deviation from plan R10's no-cookie domain, with the evidence above).

## B. A choice on feed media rows
- Labels move to one pure helper, `lib/recLabels.ts`: `originalLabel({format, source})` →
  "Watch on YouTube" / "Listen on Apple Podcasts" (or the host's name) / "Open original", and
  `sourceLabel(host)`; `UpNext.tsx` imports them (its own copies removed).
- `Row` gains an optional `choice?: {label: string, href: string, onClick?: () => void}`. When
  set, the meta line shows two actions before the time: a button **"Open in Gloss"** (calls
  `onOpen`, same as the title) and a link with `choice.label` and the external icon (new tab,
  `rel="noopener noreferrer"`, visually-hidden "(opens in a new tab)"). Both are real controls
  (keyboard, focus ring from existing tokens, ≥ 44 px target on touch via padding).
- `ForYouTab`: a `video` or `podcast` item with `opensHere(item)` passes `choice` (the original's
  URL; `onClick` sends `rec_clicked`, as the title does). A media item that can't open here
  (longer, or unknown length) is unchanged: the title opens the original, no "Open in Gloss".
  Articles unchanged.
- Up next: a media item that opens here shows `originalLabel(item)` ("Watch on YouTube")
  instead of "Open original" next to "Open here". Nothing else in Up next changes.
- Main bundle ≤ 150 KB gzip (149.48 now): `Row` and `ForYouTab` are in it; the change must stay
  under ~0.3 KB. `recLabels.ts` adds no dependency.

## Tests (vitest, written first)
- `recLabels`: video, Apple, Spotify, unknown host, article.
- `Row`: with `choice`, "Open in Gloss" calls `onOpen` and the link has the href, target and
  hidden text; without `choice`, neither renders.
- `ForYouTab`: an `open_here` video row shows both; a long video row (`open_here: false`) shows
  neither and its title links to YouTube in a new tab; an article row unchanged.
- `media.test`: the embed URL's origin is `https://www.youtube.com`; a message from
  `https://www.youtube-nocookie.com` (old origin) or another source is ignored.
- Up next: an `open_here` video shows "Open here" and "Watch on YouTube".

## Acceptance
1. Web suite, typecheck, annotator and extension suites green; main bundle ≤ 150 KB.
2. Emulator harness: `tools/shots/media.py` on T05 still passes (seek loads the player at the
   paragraph's time, now on `www.youtube.com`); a For you shot at 1440 and 390 (light, dark)
   with a short and a long video row: axe 0, no horizontal scroll.
3. milestone-reviewer SHIP → PR → CI green → merge → `make deploy-web` (Sourabh's yes).
4. Live: Sourabh plays a video in Gloss on the live site (signed in to YouTube) and opens a
   feed video both ways.

## Production writes
None beyond the web deploy.

## Risks
- YouTube may still challenge signed-in viewers on some networks; "Open on YouTube" remains.
- Readers signed in to YouTube are now identifiable to YouTube when they press play (the privacy
  page says so).

## Round 1 (plan-reviewer REVISE, 7 items; all applied, these override the sections above)

**F1. Bundle.** `ForYouTab` is a lazy chunk (`LibraryPage.tsx` lazy-loads it); only `Row` (via
`libraryRows.tsx`) and `UpNext` are in main, with 0.52 KB of headroom. So `Row` gains a generic
`actions?: ReactNode` slot rendered in the meta line before the time (no `choice` prop); the two
controls are built in `ForYouTab` and land in its chunk. STATUS §25 records main and ForYouTab
chunk sizes before and after.

**F2. Accessibility.** The button: visible "Open in Gloss", `aria-label={`Open in Gloss: ${title}`}`,
`disabled` while that row is opening (no second `openWeb` or `rec_clicked`). The link: visible
`originalLabel`, then visually hidden `: {title}` and " (opens in a new tab)" (the visible label
starts the name, WCAG 2.5.3). CSS in `src/styles/library.css` beside `.row__meta`: existing
focus-ring token; 44 px targets under `@media (pointer: coarse)` only.

**F3. Player tests (`test/media.test.tsx`).** The assertion that a message from
`https://www.youtube.com` is ignored is **removed** (it is now the accepted origin). The URL and
iframe tests compare with the literal `"https://www.youtube.com"`, not the constant, and are
renamed (no "no-cookie"). Rejected origins: `https://www.youtube-nocookie.com`,
`https://youtube.com`, `https://m.youtube.com`, `https://www.youtube.com.evil.example`. The
iframe's `referrerpolicy` is asserted `strict-origin`.

**F4. Feed tests.** `Row`: the `actions` slot renders where expected and nothing without it.
`ForYouTab` (or a small exported `MediaChoice` component in its chunk): "Open in Gloss" calls
`openWeb` once and is disabled while busy; both accessible names include the title; the link
sends `rec_clicked` exactly once and opens the URL in a new tab; an `open_here` podcast from
`podcasts.apple.com` shows "Listen on Apple Podcasts"; an `open_here: false` video shows neither
control and its title links to YouTube in a new tab; an article row is unchanged.

**F5. Evidence that proves the claims.** `tools/shots/media.py`: also asserts
`new URL(iframe.src).origin === "https://www.youtube.com"`. New `tools/shots/media_followup.py`:
a demo reader's For you tab with `/v1/feed` answered over CDP (`Fetch.requestPaused`) from a
committed fixture (`tools/shots/fixtures/feed_media.json`: one `open_here: true` video, one
`open_here: false` video, one article); no search, no LLM. At 1440 and 390, light and dark: axe 0
at every impact, no horizontal scroll; keyboard: Tab reaches "Open in Gloss" with a visible focus
ring, then the YouTube link; the long video row has neither control. Shots into
`docs/evidence/media-followup/`.

**F6. Docs.** DESIGN §21.4: the player on `www.youtube.com` (click to load stays), and media rows
within the caps offer "Open in Gloss" and the original; long or unknown-length ones stay
original-only. STATUS: decision **55** in §10 (2026-10-14, Sourabh's words: the second embed
"the second one", feed "keep long ones as YouTube only"), overriding plan R10 and BUILD_PLAN's
"privacy-enhanced domain" line; §1 row; §25 acceptance. Stale comments fixed: `embedUrl`'s
"no-cookie domain" and `RowProps.onOpen`'s "Read here for web articles".

**F7. Privacy page, stated as it is.** Videos section keeps the thumbnail sentence, then: the
player loads only when you press play, from YouTube; YouTube is told the player is on Gloss's
site; once you press play YouTube may set cookies, and if you're signed in to YouTube in this
browser it can link the view to your account, as with any embedded video. A web test asserts the
Videos section no longer says "no-cookie".

**Nits taken:** `originalLabel` derives the podcast app from `new URL(item.url).hostname`, not
`source`. The player's link stays "Open on YouTube" (it sits under a YouTube player); the feed
says "Watch on YouTube", as Up next's long-video button already does. Up next keeps "Open here"
(unchanged, not in scope).
