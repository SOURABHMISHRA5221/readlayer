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
