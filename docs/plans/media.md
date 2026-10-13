# Media: YouTube videos and podcasts in Gloss (decision 54, Sourabh 2026-10-13)

## Context
Sourabh: "someone can view youtube videos and podcast too on our platform and we will analysis its
transcript to suggest meaning before/after this just like the article thing", then "next I want
youtube and audio please". BUILD_PLAN "Media" holds the draft prompt and five things to settle.
Build day is Oct 14, before M9 (Oct 15, growth and extension fix); freeze Oct 16.

A reader opens a YouTube video or a podcast episode inside Gloss: the player on the page, the
transcript under it as the text, and the same overlay as an article on that transcript ("Before
you watch / listen", notes on the spans this reader is likely to miss, recap and Up next). The
transcript is the content: stored as paragraphs with start times, never rewritten or summarised.
Demands, linking, growth, scoring, explanations and the verifier are reused unchanged.

## Evidence gathered before planning (2026-10-13, local, real Vertex, production ledger)
15 paid calls and 3 refused ones, **$0.56** in the spend ledger (day total $0.65 of $8). Scratch
script, not committed; it called LiteLLM directly because `llm.py` has no media call yet, with
the budget check before and the ledger write after every call. Two temporary audio objects were
put in `gs://readlayer-sourabh-26-graph/tmp/measure-media/` and deleted (Sourabh's yes on each
delete prompt); the bucket holds only the two concept files again. Read-only: `rec_cache`.

| # | Input | Model, settings | Tokens in / out | Time | Cost | Result |
|---|---|---|---|---|---|---|
| 1 | YouTube, 16 min (`d6fUwCBvVc0`) | fast, defaults | 87,664 (63,360 video, 24,003 audio) / 4,448 | 34 s | $0.037 | Complete, but start times came back as MMSS written as integers (15:49 → 1549) |
| 2 | same | fast, 1 frame / 10 s, low detail | 30,662 (6,336 video) / 4,943 | 19 s | $0.022 | Same words (97.6% agreement with 1) |
| 3 | same | quality, as 2 | 30,662 / 3,300 | 29 s | $0.035 | 96.1% agreement with 2; 41 proper paragraphs (fast: 114 one-sentence ones) |
| 4 | Podcast, 4.6 min, 5.6 MB MP3, inline | fast | 7,263 / 929 | 8 s | $0.0045 | Complete |
| 5 | same, by its public link | fast | same | 9 s | $0.003 | Vertex fetched it itself |
| 6 | 20 MB, 32 MB and 87 MB podcast files by link | fast | — | — | $0 | 400 each: a link works only for small files |
| 7 | Podcast, 22.5 min, 32 MB, from `gs://` | fast | 34,016 / 9,760 | 40 s | $0.035 | Complete (4,081 words, last start 22:08) |
| 8 | YouTube, 68 min (`xFPILM4UUSg`), one call | fast, as 2 | 129,038 / 65,522 | 242 s | $0.20 | **Failed**: hit the output limit; from 56:07 it repeated text first given at 31:48; times ran to 184 min |
| 9 | same, window 50:00–60:00 (`start_offset` / `end_offset`) | fast, twice | 19,284 / 1,742 | 18 s, 183 s | $0.010 | **1,219 and 1,124 words: a third of the speech missing**, no error |
| 10 | same window | quality, default thinking | 19,284 / 5,754 (3,040 thinking) | 42 s | $0.036 | 1,852 words; its last words join window 60:00's first words exactly |
| 11 | same window | quality, `reasoning_effort: low` | 19,284 / 2,722 | 23 s | **$0.025** | 1,753 words, 94.7% agreement with 10; of the ~100 missing, 65 are "uh" / "um" and one 9-word aside |
| 12 | 48-min podcast from `gs://` with the same offsets | quality | 71,427 audio / 8,000 (limit) | 106 s | $0.084 | **Offsets are ignored on audio**: the whole file was read and the call overran |
| 13 | 10-min MP3 piece cut at frame boundaries (9.6 MB), inline | quality, low | 15,324 / 2,418 | 23 s | **$0.021** | Complete (1,571 words), times counted from the piece's start |
| 14 | 10-min piece at 192 kbps (14.4 MB), inline | quality, low | 15,324 / 3,596 | 31 s | $0.025 | Accepted and complete: 14.4 MB inline is inside the request limit |

What this fixes:
- **Rates.** Audio is 25 tokens a second. Video frames at 1 per 10 s and low detail add 6.6.
- **LiteLLM 1.104 leaves audio tokens out of its cost** for these models (the difference in runs
  1–3 is exactly `audio_tokens × input price`). The budget guard would under-count media by
  40–75% of the input cost unless `llm.py` adds them.
- **The fast model is not safe for transcripts** (rows 9): it drops speech silently. Transcripts
  use `MODEL_QUALITY`, with no fallback.
- **One call per recording does not scale** (row 8). Ten-minute windows do (rows 10–14), cost
  about **$0.025 per 10 minutes** and run in parallel.
- **Podcasts need no bucket.** A link works only for small files and offsets do nothing on
  audio, but an MP3 cut into pieces at frame boundaries and sent inline works (rows 13, 14).
- **Times must be asked for as `MM:SS` text** and converted in code (row 1).

Cached search results (`rec_cache`, 619 videos, 146 podcast links):
- Video length: median 7.4 min; 82% ≤ 15 min, 90% ≤ 20, **95% ≤ 30**, 99% ≤ 60. Many are in Hindi.
- Podcast links: 106 Apple (only **19 episode links**, 87 show pages), 36 Spotify, 4 other.
  Apple's public lookup (`itunes.apple.com/lookup?id=<show>&entity=podcastEpisode&limit=200`)
  resolved **15 of 19** episode links to an audio file (misses are episodes older than a show's
  latest 200): 13 MP3, 2 M4A; median 22 min, 9 of 15 ≤ 30 min, **12 of 15 ≤ 45 min**; files
  1.8–87 MB; one host answered 403. Spotify gives no audio file.
- The site sends no Content-Security-Policy today (`firebase.json` has `X-Frame-Options`,
  `nosniff` and a referrer policy only), so BUILD_PLAN's "`frame-src` changed" has nothing to
  change. Adding a CSP is not part of this plan.

## Decisions this plan takes (BUILD_PLAN's five open points)
1. **Transcript source and cost.** Gemini on Vertex reads the YouTube URL or the MP3 pieces,
   task `transcribe` on `MODEL_QUALITY`, `reasoning_effort: low`, no fallback. About $0.025 per
   10 minutes: a 20-minute video ≈ $0.05, a 30-minute one ≈ $0.075, a 45-minute episode ≈ $0.11,
   plus the usual analysis. **Sourabh, 2026-10-13: "yes"** to paying per recording at these
   prices, inside `LLM_DAILY_BUDGET_USD` and the caps in §E. Superseded by round 2, item 5
   (the estimate roughly doubled; what he was told and answered is recorded there).
2. **A model transcript is not the speaker's exact words.** The page says so under the title:
   "Transcript made by Gemini from the recording. It can contain errors, and filler words are
   often left out." Card labels read "What the speaker is saying" and "Explanation — not the
   speaker's words". The verifier checks restatements against the transcript text, as it does
   against article text. **No explanation or judge prompt changes** (eval integrity: their
   versions, caches and eval results stay as they are).
3. **Playback.** YouTube's own player from `youtube-nocookie.com` in an iframe, driven by
   `postMessage` (no third-party script on our origin). Podcasts: `<audio>` from the publisher's
   file, nothing re-hosted. The current paragraph is marked and followed; each paragraph's time
   is a button that seeks.
4. **Long recordings.** Ten-minute windows, four at a time. Caps: video ≤ 30 min, audio ≤ 45 min
   and ≤ 70 MB. Three requests, each ordinary (nothing runs after a response): open (≈ 1 s) →
   transcribe (the player is already usable) → analyse (as today).
5. **Not in scope:** the extension, downloads, live streams, recordings without speech,
   non-English recordings, Spotify, M4A and other non-MP3 audio, Apple show pages (the
   "latest episode" stretch item is dropped, R12).

## A. Media URLs and metadata (`app/media/urls.py` pure, `app/media/sources.py` I/O)
- `classify(url) -> YouTube(video_id) | ApplePodcast(show_id, episode_id | None) | AudioFile |
  None`. YouTube: `youtube.com/watch?v=`, `youtu.be/`, `/shorts/`, `/embed/` on the bare,
  `www.` and `m.` hosts (not `music.`), id = 11 chars of `[A-Za-z0-9_-]`. Apple: `podcasts.apple.com/…/id<digits>`
  with optional `?i=<digits>`. `AudioFile`: an https URL whose path ends `.mp3`. Anything else is
  an article, as today.
- Canonical URL → `content_id = url_hash(canonical)`, so every spelling shares one transcript:
  `https://www.youtube.com/watch?v=<id>`; `https://podcasts.apple.com/podcast/id<show>?i=<episode>`;
  an audio file's normalised URL.
- **YouTube metadata**: one `videos.list` call, `part=contentDetails,status,snippet` (1 quota
  unit, the existing server-side key, counted in the search ledger as one `youtube` call, not
  against `YOUTUBE_SEARCH_DAILY_CAP`, which guards `search.list`). Refuse, before any model
  call: not found or not `public`; `status.embeddable` false; `liveBroadcastContent` not `none`;
  an age rating; duration missing, under 30 s or over `MEDIA_MAX_VIDEO_S`; `defaultAudioLanguage`
  present and not `en*`. Kept: title, channel, thumbnail URL, published date, duration.
- **Apple lookup**: GET the fixed host `itunes.apple.com/lookup` with the two numeric ids
  (built by us from digits only, so not a user-supplied URL; plain `httpx` with
  `SEARCH_TIMEOUT_S`, like the search providers; no key, no reader data). Episode = the result
  whose `trackId` matches; needs `episodeUrl`. Refuse: no match (`episode_not_found`), no
  `episodeUrl`, `episodeFileExtension` not `mp3`, `trackTimeMillis` over `MEDIA_MAX_AUDIO_S`.
  Kept: episode title, show name, artwork URL, release date, duration, `episodeUrl`.
  A show page (no `i=`) is refused with `not_an_episode` ("Open original").
- **Audio pre-check** (`safe_fetch.audio_head`): a ranged GET of the first 64 KB through the SSRF
  guard. Refuse unless the final response is `audio/mpeg` (or `audio/mp3`), `Content-Length` (or
  the range total) is present and ≤ `MEDIA_MAX_AUDIO_BYTES`, and the bytes hold an MP3 frame.
  When the lookup gave no duration, estimate it from the first frame's bitrate and the length
  and apply the cap to that.

## B. Fetching audio (`app/ingest/safe_fetch.py`)
`SafeFetcher.fetch_audio(url) -> FetchedAudio{final_url, body}` and `audio_head(url)`: the same
per-hop validation, public-IP check, pinned connect and robots.txt rule as pages, with their own
limits: `MAX_AUDIO_REDIRECTS = 6` (enclosures chain measurement prefixes; 2 hops seen),
`AUDIO_TIMEOUT_S = 45` overall, body read in chunks and cut off at `MEDIA_MAX_AUDIO_BYTES`
(70 MB; Cloud Run has 1 GiB). Content type must be `audio/mpeg` / `audio/mp3`. The bytes live
only for the transcribe request: never stored, never logged.

## C. MP3 pieces (`app/media/mp3.py`, pure)
`split(data, max_seconds=600, max_bytes=13_000_000) -> list[Piece{start_s: float, data}]`: skip
an ID3v2 tag, walk Layer III frame headers (MPEG 1, 2 and 2.5 tables; resync on junk), cut on a
frame boundary when either limit is reached; `duration(data)` from the same walk. Pieces are
`memoryview` slices (no copy). Under 30 s of frames in total, or less than 90% of the bytes
inside frames → not an MP3 we can read → refused. The exact duration from the walk is checked
against `MEDIA_MAX_AUDIO_S` again here (the pre-check's figure can be wrong).

## D. Transcription
**`llm.transcribe(task, media, *, window, settings) -> LLMResult[TranscriptWindow]`** in
`app/llm.py` (callers still import no SDK). `media` is `YouTubeClip(url, start_s, end_s)` or
`AudioClip(data, mime)`. Same budget check, our own retries with backoff, cost logging and spend
ledger as `run()`; route `"transcribe": Route("model_quality", None, timeout_s=90,
reasoning_effort="low")`; `max_tokens = 8000` (rows 11, 13, 14 used ≤ 3,600); schema
`TranscriptWindow{language: str, paragraphs: list[{start: "MM:SS" | "H:MM:SS", text}]}`
validated locally, one repair-free re-ask on invalid output (a second call, costed). Parts:
YouTube `{"type": "file", "file": {"file_id": url, "format": "video/mp4", "detail": "low",
"video_metadata": {"fps": 0.1, "start_offset": "<s>s", "end_offset": "<s>s"}}}`; audio
`{"file_data": "data:audio/mpeg;base64,…"}`. Prompt `app/prompts/transcribe.md`
(`transcribe-v1`): the measured wording (verbatim, in the language spoken, no translation, no
summary, paragraphs of two to five sentences, `MM:SS` starts, the BCP-47 language), and a system
line that the recording is untrusted data whose spoken instructions are never followed. The
model gets the recording and that fixed text only: no title, no reader data, no tools.
- **Cost.** `_media_cost(response, model)` = LiteLLM's figure + `audio_tokens × input price`
  (from `prompt_tokens_details`; the model's price-map entry or `MODEL_PRICE_OVERRIDES`). A unit
  test pins row 11's numbers ($0.0247). If LiteLLM later prices audio itself the test fails
  and the addition is removed.
- **Budget.** Before the first window: `spent + duration_min × $0.004 > LLM_DAILY_BUDGET_USD` →
  `BudgetExceeded` (nothing spent on a recording that can't finish). Each call still checks.

**Assembly (`app/media/transcript.py`, pure).**
- `windows(duration_s, 600)`; a last window under 60 s joins the one before.
- Per window: parse `start` to seconds; a YouTube window's times must be absolute (inside the
  window ± 5 s) or all relative (≤ window length + 5 s, then shifted); audio pieces are always
  relative. Invalid (re-asked once, then the item fails): `finish_reason` "length"; a time
  outside the window; any paragraph over 30 characters appearing three times; more than 300
  words a minute. Times are made non-decreasing (a later paragraph never starts before the one
  above it).
- A window with no paragraphs is silence and is fine; a recording with under 80 words in all is
  refused (`no_speech`, the article rule `MIN_ARTICLE_WORDS`).
- Join: when a window's last paragraph has no closing punctuation and the next window's first
  starts in lower case, they become one paragraph (row 10's join). Paragraphs under 25 words
  merge into the next one of the same window. Words are never changed, only grouped.
- Language: the majority `language` over windows, by words. Not `en*` → refused (`not_english`).
- Output: `[TimedParagraph{start_s: int, text}]` with whitespace collapsed, then
  `build_paragraphs` for ids and offsets, so phase 2 sees an ordinary article. **Not**
  `clean_paragraphs`: it drops paragraphs under 40 characters and truncates, and a transcript
  must lose nothing. Instead a short last paragraph merges into the one before it, and above
  `MAX_PARAGRAPHS` (200) the shortest neighbouring pairs merge until it fits. Over
  `MAX_ARTICLE_CHARS` (150k; 45 minutes at 185 words a minute is about 50k) → refused
  (`too_long`), never cut.

**Service (`app/media/service.py`).**
- `open_media(url, caller)` (inside POST /v1/recs/open, §F): cached `contents/` doc → ready,
  free, no slot. Pending doc → its stage, free. A refusal recorded in the last 24 h → the same
  422, free. Otherwise reserve a media slot (§E), run §A's checks (refusal → slot refunded,
  nothing stored), and store `pending_contents/{id}` with `stage: "transcribe"`, the `media`
  block, no paragraphs, `source: user_ingested`.
- `transcribe_pending(content_id)`: the pending doc's existing lease (`acquire` / `release`,
  attempts ≤ 3) with `TRANSCRIBE_TIMEOUT_S = 150` plus the 30 s margin. Audio: `fetch_audio`,
  `mp3.split`. Windows run four at a time. Success → the pending doc gets its paragraphs (with
  `start_s`), `stage: "analyse"`, and the transcript record (model, prompt version, windows,
  cost). A refusal found here (`not_english`, `no_speech`, not an MP3, too long once measured,
  a fetch error) marks the pending doc `refused: <code>` and leaves it for its 24 h TTL, so the
  same URL is not paid for again that day; the slot is not refunded once a model call ran.
  Budget refusals and a cancelled request release the lease without counting an attempt.
- Phase 2 is today's `analyse_pending`, unchanged except that it requires `stage != "transcribe"`
  and copies `media` and `start_s` into `contents/{id}`.

**Stored shape (DESIGN §3).** `ContentDoc.media: Media | None` = `{kind: "youtube" | "audio",
video_id?, audio_url?, duration_s, transcript: {model, prompt_version, windows, cost_usd,
made_at}}`; `StoredParagraph.start_s: int | None`; `PendingDoc` gains `media`, `stage`,
`refused`, and `PendingParagraph.start_s`. Content only, no uid. Old docs read as before
(defaults). `llm_calls` carries the transcribe calls. `image` = the thumbnail or artwork URL.

## E. Caps (settings in `config.py`, defaults; all in `deploy.env.yaml` so they are visible)
| Setting | Default | Why |
|---|---|---|
| `MEDIA_ENABLED` | true | Kill switch: false → media URLs are refused with "Open original" |
| `MEDIA_MAX_VIDEO_S` | 1800 | 95% of cached videos; 3 windows ≈ $0.075 |
| `MEDIA_MAX_AUDIO_S` | 2700 | 12 of 15 resolved episodes; 5 windows ≈ $0.11 |
| `MEDIA_MAX_AUDIO_BYTES` | 70,000,000 | 45 min at 192 kbps is 65 MB |
| `MEDIA_DAILY_CAP` | 5 | New recordings per signed-in reader per UTC day (≤ $0.70 with analysis) |
| `ANON_MEDIA_DAILY_CAP` | 1 | Per demo reader |
| `ANON_GLOBAL_MEDIA_DAILY_CAP` | 10 | All demo readers together (≤ $1.40 a day) |
Counters: `users/{uid}/media_counts/{day}` through the existing generic `reserve_daily` /
`refund_daily`, added to `USER_SUBCOLLECTIONS` (export and delete walk it; the existing test
that fails on an uncovered subcollection covers it), and `ops/media/days/{day}` for the shared
anonymous count. A recording does not also take an article ingest slot. Growth slots are
reserved as for an article (`reserve_growth`). Past a cap: 429 `media_cap_reached` with the
"Open original" wording. The `$8` budget guard stays the hard stop.

## F. API (DESIGN §8)
- **POST /v1/recs/open** `{url}`: classifies first; a media URL goes to `open_media`. Response
  gains `kind: "article" | "video" | "podcast"` and `stage: "transcribe" | "analyse" | null`
  (`ready` as today). New 422 codes with a reader-facing message each: `not_embeddable`,
  `too_long`, `not_public`, `live`, `not_english`, `no_speech`, `episode_not_found`,
  `not_an_episode`, `unsupported_audio`, `media_off`; 429 `media_cap_reached`. Feed rows, Up
  next and Read any link all use this one route.
- **POST /v1/content/{id}/transcribe**: 200 `{status: "analysing"}` when the transcript is
  stored (no model call if it already is), 202 while another request holds the lease, 410 after
  3 failed attempts, 422 with the refusal code, 429 on the budget, 504 on the timeout. Same
  access rule as `…/analyse`.
- **GET /v1/content/{id}**: `status` gains `"transcribing"` (paragraphs empty); `media: {kind,
  video_id | audio_url, duration_s} | null`; paragraphs gain `start_s`. Annotations and
  recommendations keep answering 409 until ready.
- **GET /v1/feed** and **…/recommendations**: items gain `open_here: bool`, computed at serve
  time by `classify` and the duration cap (so stored demo snapshots need no rewrite): a YouTube
  video within the cap, an Apple episode link. Spotify and show pages stay "Open original".
- Library rows (`GET /v1/content`) gain `format: "article" | "video" | "podcast"`.
- Rate limits: the transcribe route shares the general per-uid limit; nothing new.

## G. Web (`apps/web`) and annotator
- **Annotator** (`packages/annotator`): `labels?: {author?, card?}` option overriding
  `AUTHOR_LABEL` and `CARD_LABEL`; nothing else changes, the extension passes nothing and is not
  rebuilt or re-released. Version 0.9.0.
- **`lib/media.ts`** (pure, unit-tested): `paragraphAt(starts, t)` (binary search), `clock(s)`,
  the YouTube message codec (`listening`, `seekTo`, `playVideo`; `infoDelivery` → current time)
  with a strict origin check (`https://www.youtube-nocookie.com`), `openable(item)`.
- **`components/reader/MediaPlayer.tsx`** (in the reader's lazy chunk): YouTube iframe
  (`/embed/<id>?enablejsapi=1&origin=<our origin>&rel=0`, `title`, `allow="encrypted-media;
  picture-in-picture"`, `referrerpolicy="strict-origin"`), or `<audio controls preload="none"
  referrerpolicy="no-referrer">`. Exposes `seek(s)` and a `time` callback (audio: `timeupdate`).
  Sticky at the top of the text column (16:9 capped at 40vh; the audio bar is one row); a
  failed audio load shows "This episode's audio couldn't be played here" with Open original.
- **ReaderPage**: with `media`, the header kicker reads "Video · 16 min · channel" / "Podcast ·
  22 min · show", the disclaimer line sits under it, the player above the body. Status
  `transcribing` → the player is usable at once and the body shows the existing preparing
  notice worded "Gloss is listening to this. About a minute."; the page calls `…/transcribe`,
  then reloads the content and continues with `…/analyse` exactly as today. Transcript body =
  today's `ArticleBody` plus a time button per paragraph (`data-rl-ui`, so anchors and copy
  ignore it; `aria-label="Play from 12:40"`). The paragraph being spoken gets `data-rl-now` (a
  rule and tint from existing tokens) and is kept in view while playing, unless the reader
  scrolled in the last 5 s; a "Follow" toggle turns it off. Reduced motion: no smooth scroll.
  `PrereadPath` takes its heading as a prop ("Before you watch" / "Before you listen"). Recap
  and Up next unchanged.
- **Entry points**: `ForYouTab` and `UpNext` show "Open here" when `open_here`; Read any link's
  placeholder becomes "Paste an article, YouTube or podcast link" and shows the API's message
  on a refusal. Library rows show a Video / Podcast badge.
- **Privacy page**: one line each: videos play in YouTube's player (YouTube sees the reader's
  IP and sets nothing until play, on the no-cookie domain); podcast audio streams from the
  publisher; transcripts are made by Gemini on Google Cloud from the public recording only.
- Budget: the main bundle is 148.43 KB of 150. The player and media reader code live in the
  reader's lazy chunk; the check is part of acceptance.

## Privacy, safety and cost (summary)
- No reader data reaches a model, YouTube's API or Apple's lookup: prompts get the recording
  and fixed instructions; the lookups get public ids. Logs: `uid_hash`, content id, counts,
  cost; never transcript text or URLs with query strings.
- Spoken content is untrusted: system line, schema validation, no tools; downstream prompts
  wrap the transcript in the content delimiters like any article.
- Transcripts are `user_ingested`: private to readers who opened them (§17.4), shared so a
  second opener pays nothing, never corpus or eval data.
- No LLM on the scoring path; `reader/` and `scoring/` untouched.
- No new bucket, secret, IAM binding, Firestore index or TTL policy. `pending_contents`
  already has its TTL.
- Worst day: anonymous 10 recordings ≈ $1.40; each signed-in reader ≤ $0.70; hard stop $8.

## Tests (offline: fake LiteLLM, fake transports, fake stores; no network)
- `test_media_urls.py`: every URL form, canonical ids, look-alike hosts refused.
- `test_mp3.py`: synthetic frame streams (CBR, VBR, MPEG 2, ID3 tag, junk between frames):
  frame lengths, exact durations, cuts on boundaries, both limits, non-MP3 refused.
- `test_transcript.py`: clock parsing; absolute vs relative windows; each invalid case; the
  mid-sentence join; short-paragraph merge; monotone times; language majority; `no_speech`;
  window planning; words unchanged (the multiset of words in equals the multiset out).
- `test_llm_transcribe.py`: parts built as specified; route and effort; `max_tokens`; cost with
  audio tokens (row 11); ledger writes per attempt; budget pre-check; retry classes; re-ask on
  invalid output; no fallback model is ever called.
- `test_safe_fetch_audio.py`: type, size cut-off mid-stream, 7 redirects refused, private and
  metadata addresses refused on any hop, robots.
- `test_media_sources.py`: YouTube refusals one by one; Apple hit, miss, no file, M4A.
- `test_media_service.py`, `test_media_router.py`: open → transcribe → analyse with fakes
  (media and `start_s` reach `contents/`); cache hit and pending are free; caps (per uid,
  shared anonymous) and refunds; refusal remembered for the day; lease busy / exhausted;
  budget refusal releases without an attempt; every error code and status; `open_here`.
- `test_data_rights`: `media_counts` exported and deleted (existing walk).
- Web: `media.test.ts`; `MediaPlayer` (seek posts the right message, foreign-origin messages
  ignored, audio `timeupdate`); ReaderPage states (transcribing → transcript → notes; follow
  pauses on scroll); ForYou / UpNext / ReadAnyLink openability and refusal copy. Annotator:
  labels option. `pnpm -r typecheck`, ruff, full suites green.

## Acceptance (run, not assumed; evidence into STATUS)
1. **Emulator harness, real Vertex** (`make dev-emulator`): open the measured 16-minute video
   and the measured 22-minute podcast episode (its Apple link) through Read any link.
   - Transcript complete: the video within ±10% of 1,822 words (row 3), last start ≥ 15:00;
     the podcast ≥ 3,600 words, last start ≥ 21:00; times non-decreasing, inside the duration.
   - Ledger cost per item (transcribe only): video ≤ $0.07, podcast ≤ $0.09; phase timings
     recorded (open, transcribe, analyse). **If analyse exceeds 100 s on either, lower
     `MEDIA_MAX_*` before deploy and say so.**
   - Two personas get different note counts on the same transcript; one explanation card on a
     transcript span is `verified` and labelled "What the speaker is saying".
2. A second reader opening the same two URLs: no model call (ledger unchanged), no slot used.
3. Refusals, each with its message and no model call unless stated: a Hindi video (one paid
   run, then free for the day), a 68-minute video, a Spotify link, an Apple show page, an Apple
   episode outside the latest 200, an M4A episode, `MEDIA_ENABLED=false`, the per-uid anonymous
   cap, the shared anonymous cap, the budget at $8.
4. Playback at 1440, 1024 and 390, light and dark (`tools/shots/media.py`): a time button seeks
   the YouTube player and the audio element (current time within 2 s of the paragraph's
   start); the marked paragraph follows playback; Follow pauses after a manual scroll; axe 0;
   no horizontal scroll; the transcript's words equal the stored paragraphs.
5. `uv run pytest -q`, `uv run ruff check .`, `pnpm -r typecheck`, web / annotator / extension
   suites; main bundle ≤ 150 KB.
6. **Live, after both deploys** (Sourabh's yes on each): as a Google reader, one video and one
   podcast (the two above): transcript, notes, seeking; then a demo reader opens the same two
   (cached, free). Dry-run step first: `scripts/measure_media.py --dry-run <url>` prints the
   classification, metadata checks and window plan with no model call.

## Production writes
- Done while measuring (above): 15 ledger increments on `ops/spend/days/2026-10-13`; two
  temporary objects created and deleted.
- This milestone, live check only: 2 `contents/` docs (the two recordings), 2
  `pending_contents/` docs created and deleted on the way, the opener's `ingested` (2) and
  `media_counts` (1 doc), `ops/spend` and `ops/search` increments, ≤ $0.20. Demo seeding of
  media items is Oct 16's seeding step, not this plan.
- Deploy: API from up-to-date `main` after the merge, then web; `deploy.env.yaml` gains the
  seven `MEDIA_*` lines. No migration: old docs lack the new optional fields.

## Docs
DESIGN: new §21 Media; §3 (fields, the transcribe stage), §8 (routes), §10 (`transcribe`,
media cost), §11.2 (audio fetch), §16.6 and §17.4 (opening). CLAUDE.md: `app/media/` in the
layout; cost guardrails gain "`transcribe` uses `MODEL_QUALITY`: `MODEL_FAST` dropped a third
of the speech on a measured window". STATUS §4 deviations: no CSP exists to change; transcripts
on the quality model; audio through MP3 pieces, not a bucket; Apple episode links only.

## Schedule and cut order (Oct 14) — reordered in round 1 (R12)
**YouTube end to end first, podcasts second**, so a cut at the end of the day throws nothing
away:
1. Frozen transcript cases committed (R13) → `llm.transcribe` (YouTube part, media cost,
   media budget) and `transcript.py` with tests.
2. YouTube A (urls, `videos.list`, refusals, lookup cap) → service (stages, stored windows,
   lease, refusal memory) → caps → routes and the POST /v1/content guards (R4).
3. Harness run on the 16-minute video (acceptance 1–3, video half).
4. Web: lazy media reader, click-to-load player, time buttons, follow, entry points → shots.
5. **Midday check-in with Sourabh** (status, cost so far, whether to start podcasts).
6. Podcasts behind `MEDIA_AUDIO_ENABLED`: B (audio fetch), C (MP3 pieces), Apple lookup,
   `<audio>`, the audio semaphore (R9) → harness run on the 22-minute episode.
7. `scripts/ingest_media.py` (R12) → milestone-reviewer → PR → deploy API, then web → live check.
Commit and log after each step; any of them is a /clear checkpoint.
**Checkpoint end of Oct 14 IST:** not merged → ask Sourabh what to cut (decision 27); nothing
is cut automatically. Proposed order, first to go: (1) the library badge; (2) follow-while-
playing (keep the marked paragraph and seeking); (3) "Open here" in Up next (keep the feed and
Read any link); (4) podcasts altogether, shipped with `MEDIA_AUDIO_ENABLED=false` (audio before
YouTube, as agreed). The Apple show page stretch item is dropped. M9's growth fix stays Oct 15.

## Risks
- Audio is priced by a guess ($2.50 per 1M, R6) with no billing check (2.5). If the real
  audio SKU is higher, the ledger under-counts against both the $8 guard and the $3 media
  budget by the difference.
- Phase 2 on a 45-minute transcript may pass 120 s (never run on text this long). Acceptance 1
  measures it; the caps are settings.
- Vertex may refuse some public videos (region, music claims): the item fails with "Open
  original"; three attempts at most; bounded cost.
- Enclosure hosts that block our user agent or disallow robots: "Open original". The harness
  run reports how many of the 13 resolved MP3 episodes pass the pre-check (no model call).
- Low thinking drops "um" / "uh" and, once in 1,850 words, a short aside. Said on the page.
- The explanation prompts call the source "news"; a restatement may say "the article". Looked
  at in acceptance 1; a wording change would be a new prompt version with its eval, so M9 or
  later, not here.

## Round 1 (plan-reviewer REVISE, 15 items; all applied, these override the sections above)

Checked before applying (2026-10-13, read-only): `contents/` holds 353 docs and none has a
YouTube, Apple Podcasts or Spotify URL; `pending_contents/` is empty. So no stored article can
collide with a media content id. `App.tsx` imports `ReaderPage` eagerly (it is in the main
bundle). LiteLLM 1.104 has **no audio price** for either model (only `supports_audio_input`),
and Vertex's pricing page, as searched, gives Gemini 3.8 Flash $0.75 / $3.75 per 1M tokens
(introductory, until 2026-12-31; $1.5 / $7.5 from 2027-01-01) with no audio line found.

**R1. Stages and attempts.** The pending doc gets `transcribe_attempts` (≤ 3) beside the
existing `attempts`, which stays phase 2's. `acquire` / `release` take the stage and count only
that stage's field. `acquire` writes a random `lease_token` with `lease_until`; every write the
transcribe run makes is a transaction that first checks the token is still ours. The success
write, in one transaction: paragraphs (with `start_s`), `stage: "analyse"`, `attempts: 0`,
`lease_until` and `lease_token` cleared, the transcript record. `TRANSCRIBE_TIMEOUT_S = 150`
wraps the audio fetch, the split, every window and that write; the lease is 180 s, so it
always outlives the run.

**R2. Paid work is never thrown away, and never free to repeat.**
- Each finished window is written to the pending doc as it completes
  (`windows: {"<index>": [{start_s, text}]}`, ≤ 150k characters in all, well under 1 MiB). A
  retry transcribes only missing windows; assembly runs when all are present.
- A transcribe run counts an attempt whenever **any** call was billed in it, including a
  cancelled request, the timeout and a budget refusal after the first window. Only a run that
  billed nothing (budget refused up front, busy lease) is free.
- `transcribe_cost_usd` on the pending doc adds up every billed call. Before each window is
  launched: `cost so far + in-flight estimates + this window's estimate` must stay within
  `2 × duration_min × MEDIA_EST_USD_PER_MIN`, else the item fails (`too_costly`, remembered).
- **Worst case per item** = that ceiling: with `MEDIA_EST_USD_PER_MIN = 0.006` (R6), a 30-min
  video ≤ $0.36 and a 45-min episode ≤ $0.54 across all attempts, against $0.18 and $0.27
  expected. The happy-path cap totals in §E are replaced by the media budget (R7).

**R3. Order of checks and what GET shows.**
- `open_media` checks, in order: cached `contents/` doc **with `media` set** → ready;
  remembered refusal (R5) → the same 422, free; pending doc not past `expire_at` and not
  `refused` → its stage, free; otherwise new. A pending doc past `expire_at` (TTL can lag a
  day) or `refused` counts as gone.
- New `PendingRepo.create_media(doc)`: one transaction that creates, or overwrites a doc that
  is expired or refused; any other existing doc is returned unchanged. Media never goes
  through `_store_pending` (its 80-word check needs paragraphs).
- GET /v1/content/{id}: `status` is `"transcribing" | "analysing" | "ready" | "refused" |
  "failed"`; `refused` carries `{code, message}`, `failed` means attempts are exhausted. The
  reader page shows the message with "Open original" for both and stops calling.

**R4. Other paths that read pending docs by URL hash.**
- POST /v1/content, both shapes (server fetch and extension text): a URL that `classify` calls
  media → 422 `use_open_here` ("Open it in Gloss with Read any link."), before `is_known` and
  before any slot. The extension shows the API's message as it does today; no extension
  change or release. (`redact_url` keeps the `v=` id, so an extension YouTube page would
  otherwise hash to the media doc's id.)
- `analyse_pending` on a doc with `stage == "transcribe"` raises `ContentTranscribing` → 409
  `content_transcribing` (its own status, never an attempt).
- Annotations, recommendations, explain, saved and the library already treat a pending doc as
  not ready (409 / not listed); a media pending doc has no paragraphs and is listed nowhere.
  A test covers each with a transcribe-stage doc.

**R5. Lookups have their own counter, cap and memory.**
- `videos.list`, the Apple lookup and the 64 KB audio head are counted in
  `ops/search/days/{day}` under their own field `media_lookup` (the existing `extra`
  argument), never in `calls` or `youtube`, so the search caps that feed and Up next use are
  untouched.
- `MEDIA_LOOKUP_DAILY_CAP = 300` shared by everyone; past it media URLs answer 429
  `media_cap_reached` with "Open original".
- Refusals from §A are remembered for the UTC day in `ops/media/days/{day}`
  (`refused: {content_id: code}`, ≤ 300 entries by the lookup cap, no uid). A repeat open of a
  refused URL is answered from there: no lookup, no slot.

**R6. Pricing audio honestly.**
- New setting `MODEL_AUDIO_PRICE_OVERRIDES: dict[model, usd_per_token]`; `_media_cost` = text
  and video tokens at LiteLLM's input price + audio tokens at LiteLLM's
  `input_cost_per_audio_token` when present, else the override, **else refuse the call**
  (`LLMRejected("no audio price")`) so an unpriced call can never reach the ledger as cheap.
- Sourabh, asked to read the audio SKU off the billing report, answered "mark 3 dollar
  budget" (2026-10-13): no billing check; the cautious price stays and R7's $3 media budget
  bounds what an under-priced call could cost. `deploy.env.yaml` sets the quality model's audio price to
  **$2.50 per 1M** (3.3 × its text input price, the audio-to-text ratio of the last Gemini
  Flash price list I know). That makes a 10-minute window ≈ $0.051 (15,000 audio tokens
  $0.0375 + 3,960 video $0.003 + 2,700 output $0.010), so `MEDIA_EST_USD_PER_MIN = 0.006`.
  If the bill shows audio at the text price, both go down and nothing else changes.
- Tonight's ledger figure ($0.56) used the text price for audio and may be low by up to about
  $0.40; recorded as such in STATUS.
- A transcribe call that times out or is cancelled adds its window's estimate to the ledger
  (Vertex may still bill it).

**R7. Media can't eat the demo's budget.** `MEDIA_DAILY_BUDGET_USD = 3` (**Sourabh: "mark 3
dollar budget"**, 2026-10-13): the ledger keeps a
separate `media_usd` for the day (new `SpendStore.add(..., media=True)`), and `open_media` and
every window check it before spending. Past it, media URLs are refused with "Open original"
and articles and explanations keep the rest of the $8. Feed and Up next items carry
`open_here: false` for anonymous readers once `ANON_GLOBAL_MEDIA_DAILY_CAP` is used (one read
of `ops/media/days/{day}` per feed request, cached 60 s per instance), so judges don't meet a
429.

**R8. Non-English is caught before paying in full.** Before any model call: refuse when the
title (YouTube) or episode title (Apple) fails the feed's existing English-only check (≥ 70%
of title letters in Latin script, DESIGN §17.1), or `defaultAudioLanguage` is set and not
`en*`. When the language is still unknown, window 1 runs alone first; a non-English window 1
stops the item (`not_english`, remembered) after one window's cost.

**R9. Memory.** A per-instance `asyncio.Semaphore(1)` around audio transcription (fetch to
assembly); a second audio transcribe on the same instance gets 202 `{status: "transcribing"}`
and the page retries in 5 s. Pieces stay `memoryview` slices, each base64-encoded only when
its window is sent. Acceptance 1 records peak RSS for the 22-minute episode (`resource.
getrusage`, logged once per run); over 600 MB → `MEDIA_MAX_AUDIO_BYTES` goes down before
deploy.

**R10. Privacy, stated as it is.**
- YouTube is **click to load**: the page shows the video's thumbnail (hotlinked from
  `i.ytimg.com` with `referrerpolicy="no-referrer"`, as the feed already does) and a play
  button; the `youtube-nocookie.com` iframe is created only on click. Before the click YouTube
  gets the thumbnail request (IP, user agent, video id); after it the player gets what any
  embed gets and may use local storage.
- Audio: `preload="none"`, so nothing is requested until play; on play the publisher and any
  measurement hosts in the episode link's redirect chain get the reader's IP and user agent,
  and the site's `strict-origin-when-cross-origin` policy sends our origin (`<audio>` has no
  `referrerpolicy` attribute; the claim is dropped).
- The privacy page says exactly this, plus that transcripts are made by Gemini on Google Cloud
  from the public recording only.

**R11. Bundle.** All media UI (player, facade, time buttons, follow, clock, the YouTube message
codec) is one `lazy()` component, `MediaReader`, imported by ReaderPage only when
`content.media` is set, like `ReadingSpine`. `lib/media.ts` is imported only from that chunk.
Entry points use the server's `open_here` only; there is no client-side `openable`. Read any
link changes only its placeholder and hint text. Acceptance 5 checks the main bundle ≤ 150 KB
and that the media chunk is not in it.

**R12. Schedule.** Reordered above: YouTube end to end first, a midday check-in, podcasts
behind `MEDIA_AUDIO_ENABLED` (default true, false = audio URLs refused with "Open original").
`scripts/ingest_media.py <url>... [--dry-run]` is built now: dry run prints the
classification, checks and window plan with no model call; the real run opens, transcribes and
analyses through the same service as the API (no reader, `user_ingested` is not used: source
`fetch`, so seeded items are library content). Oct 16's seeding then needs no new code.

**R13. Eval integrity for `transcribe-v1`.** First commit of the build:
`evals/cases/media_transcripts.yaml`, frozen: the 16-min video (reference 1,822 words from the
quality model, last start ≥ 15:00), the 22-min episode (≥ 3,600 words, last start ≥ 21:00;
its only reference, 4,081 words, came from the fast model and may be low), the 50:00–60:00
window of the 68-min video (1,753 words at low thinking, 1,852 at default; joins the next
window's first words). `transcribe-v1` is the measured wording. Any wording change reports
before and after on these same cases in the PR.

**R14. Status codes.** A budget refusal on `/transcribe` (the $8 guard or R7's media budget)
uses the existing `_ingest_error` mapping: 503 `llm_budget_exceeded` with Retry-After. 429
stays for `media_cap_reached`.

**R15. Docs, added to the list.** DESIGN §11.4 (`media_counts` among the data held, exported
and deleted), §11.5 (the per-uid, shared anonymous and lookup caps, the media budget). STATUS
§4 deviations: audio fetch limits differ from §11.2's page limits (6 redirects, 70 MB, audio
content types, 45 s); audio priced by an override until the bill confirms it. STATUS §9 video
line: two personas on the same video, notes differing, a time button seeking.

## Round 2 (plan-reviewer REVISE, 5 items; all applied, these override everything above)

**2.1 Thresholds follow the price.** §D's budget pre-check uses `duration_min ×
MEDIA_EST_USD_PER_MIN` (0.006), not $0.004. Acceptance 1's per-item transcribe caps become
`duration_min × MEDIA_EST_USD_PER_MIN`: video ≤ 16 × 0.006 ≈ **$0.10**, podcast ≤ 23 × 0.006
≈ **$0.14**. Acceptance 3 gains three refusals: `MEDIA_DAILY_BUDGET_USD` reached (no model
call), `MEDIA_LOOKUP_DAILY_CAP` reached (no lookup, no model call), and `too_costly` (forced
with a test ceiling; stops after one window).

**2.2 Every refusal is remembered, for the day, wherever it is found.** All refusal codes, from
§A, R2 (`too_costly`), R8 (`not_english` after window 1) and §D "Service" (`no_speech`, an
unreadable MP3, a failed audio fetch, `too_long` once measured), go into R5's day map
`ops/media/days/{day}.refused`. R3 changes: a `refused` pending doc **not past `expire_at`**
answers the same 422 for free; only an expired doc counts as gone and may be overwritten by
`create_media`. So within its 24 h a refused URL is never paid for again, and after UTC
midnight the day map no longer holds it but the pending doc still does until it expires. The
map is bounded by the lookup cap (≤ 300 lookups a day) plus transcribe refusals (≤ the number
of items transcribed, ≤ the media budget / $0.03), well under 1 MiB.

**2.3 Semaphore before lease.** `transcribe_pending` first tries the per-instance audio
semaphore **without waiting** (`locked()` check, then acquire); if it is taken → 202
`{status: "transcribing"}`, the lease is never touched and no attempt is counted. Only then
does it acquire the lease (the `locked()` check and `acquire()` run with no `await` between
them, so the try stays atomic on the event loop). YouTube items skip the semaphore. `test_media_service.py` covers a
busy semaphore leaving the lease and both attempt counters unchanged.

**2.4 Seeded items stay `user_ingested`, never corpus.** R12 changes: `scripts/ingest_media.py`
stores transcripts with source **`user_ingested`**, like any reader's open. Seeding only
pre-warms the shared transcript and analysis: a demo reader who opens the item from a feed
snapshot gets it free (no model call, no slot) and it is listed for that reader only (§17.4).
So the "Privacy, safety and cost" summary and §D stand as written: transcripts are never
corpus or eval data, and onboarding discover, the pre-read explainer index,
`build_landing_demo` and `measure_highlight_levels` (all corpus-only) never see them; a test
pins that a media doc is excluded from each corpus reader. "Production writes" gains a forward
note for Oct 16: `ingest_media.py --dry-run` on the demo snapshots' media items first, then at
most 6 recordings (≤ 6 `contents/` docs and 6 transitory pending docs, ledger increments, ≤ 6 ×
30 × $0.006 ≈ $1.08 inside the $3 media budget), counts stated in STATUS before running.

**2.5 What Sourabh agreed to.** After round 1 he was told the cost may be about double the first
estimate (about $0.05 per 10 minutes, a 20-minute video about $0.10) because audio's price is
unknown, that media gets its own $3 daily budget inside the $8, and was asked to read the audio
line off the billing report. His answer: **"mark 3 dollar budget"**. Recorded as: the higher
estimate accepted with spend bounded by `MEDIA_DAILY_BUDGET_USD = 3`; no billing check.

## Round 3: APPROVE (plan-reviewer, 2026-10-14); nits applied
Both nits applied: the audio-price risk line in Risks, and the atomic no-wait semaphore try
in 2.3.

## Round 4 (harness evidence, 2026-10-14; overrides everything above where it differs)
**What the harness showed** (emulator, real Vertex, `transcribe-v1`, quality model, low thinking):
the 16-minute video (`videos.list`: PT16M, 960 s; the measured transcript ends at 15:49)
planned as windows 0–600 and 600–960. Window 1: ok, 27 s, $0.049 (audio at $2.50 per 1M).
Window 2 timed out at 90 s **five times out of five**: twice inside one run (the timeout was
retried by `_MediaCall.run`, the retry cancelled by the 150 s run limit), twice on the page-style
retry, and once as a direct probe of 600–949 (ending at the real end, one attempt, no retry).
Each timeout or cancel is charged its estimate ($0.036): **$0.23 on one video, no transcript.**
With rows 9 (a 183 s offset window on the fast model) and 3 (the whole video, no offsets, 29 s),
offset windows on Vertex are not reliable enough to ship: some start offsets work (row 10,
window 1 here), some hang with no error. Ending past the real end is not the cause (the probe).

**4.1 One call per video, no offsets.** A YouTube video is transcribed in **one call on the whole
URL, without `start_offset` / `end_offset`** (row 3's shape: fps 0.1, low detail). `YouTubeClip`
gains `whole: bool`; whole → `video_metadata` carries `fps` only. The plan has one window
`[0, duration_s]`; the "window 1 alone when the language is unknown" step and the parallel
windows no longer apply to YouTube (audio pieces keep 10-minute windows and inline MP3: offsets
were never used for audio). `check_window` is unchanged (absolute and relative coincide).

**4.2 Videos over 20 minutes are refused for now.** `MEDIA_MAX_VIDEO_S` 1800 → **1200** (90% of
cached videos are ≤ 20 min; rows 3 and 8 bound the output: 16 min gave 3,300 output tokens, so
20 min stays well under `max_tokens = 8000`; row 8's 68-minute single call is what failed).
Refusal `too_long` as today ("Open original"). Raising it again needs evidence that offsets, or
a longer single call, work; not in this build.

**4.3 No retry of a timed-out media call inside a run.** `_MediaCall.run` retries transient
errors except a timeout: a timed-out window is charged its estimate once and the run fails with
504; the page's own retry (with the 2× per-item ceiling) is the only retry. A test pins one
attempt and one charge on timeout.

**4.4 Acceptance.** Acceptance 1's video half stands (±10% of 1,822 words, last start ≥ 15:00,
transcribe ≤ $0.10, analyse ≤ 100 s) and is re-run after this change on a fresh emulator. The
failed runs' spend ($0.23) is reported in STATUS. Acceptance 3's "68-minute video" refusal is now
also the 20-minute cap's case. Frozen eval cases are not edited (decision 26): T01's note ("two
windows") describes the old plan, its expectations hold; T03 (an offset window of the 68-minute
video) now tests a path the product does not use and stays as a record.

## Round 4 review (plan-reviewer REVISE, 6 items; all applied, these override Round 4)
**R4.1 Output limit and the cap's evidence.** `TRANSCRIBE_MAX_TOKENS` 8,000 → **16,000** (free
unless used; rows 7 and 14 imply ~7,200 for 20 dense minutes, so 8,000 was not "well under";
`check_window`'s 300 words a minute still catches loops). New frozen case **T04** appended to
the eval cases file before any run of it (nothing above it edited, decision 26): Dan Pink, "The
puzzle of motivation" (`rrkrvAUbU9Y`, 1,117 s, `en`), a fast, dense speaker, one whole-URL call;
no reference transcript, so a stated floor (≥ 2,600 words, last start ≥ 17:30). **Decision rule,
fixed now:** if T04 takes > 60 s or > 7,000 output tokens, `MEDIA_MAX_VIDEO_S` = **1000** (not
900: videos.list gives T01 960 s, and the acceptance video must stay openable) instead of 1200. T01 and T04 both record output tokens and latency.

**R4.2 A timed-out call ends in 504.** Only `_MediaCall.run`'s retry predicate changes (a litellm
timeout is not retried there; `classify_error` is untouched, so `run()` and `image()` keep
retrying timeouts). After charging the estimate, `transcribe` raises `MediaTimeout`
(a `TimeoutError` subclass in `app/llm.py`), so the route's existing handler answers 504
`transcribe_timeout` "Transcribing took too long. Try again."; a router test pins status and
body. Web (step 4): on 504 the page retries once automatically, then shows "Try again" and
"Open original". §G gains this line.

**R4.3 One place decides a recording's windows.** `transcript.plan_for(kind, duration_s)`:
YouTube → `[Window(0, 0, duration_s)]`; audio → `plan_windows(duration_s)`. Used by the budget
pre-check in `transcribe_pending`, by `_Run.go`, and by the dry run's window plan; unit-tested.
`YouTubeClip.start_s` / `end_s` become `int | None = None`; `None` → `video_metadata` has `fps`
only (T03 stays runnable with explicit offsets). R8's "window 1 alone" path needs no change: with
one window it is the whole run. **Risk added:** a `not_english` refusal now costs the whole
video (≤ 20 × $0.006 ≈ $0.12 estimated, ~$0.10 at window 1's measured rate), not one window;
it is still remembered for the day.

**R4.4 Cap, copy and deploy env together.** `deploy.env.yaml` `MEDIA_MAX_VIDEO_S: "1200"`
(it overrides the default); `config.py` default 1200, comment "90% of cached videos";
`refusals.py` `too_long`: "videos up to 20 minutes, podcasts 45". Plan text: §E row →
`1200 | 90% of cached videos; one call ≈ $0.10`; Decisions item 4 → "video ≤ 20 min, one call";
R2's worst case → a 20-min video ≤ $0.24 across all attempts; 2.4's seeding bound → 6 × 20 ×
$0.006 ≈ $0.72. Feed and Up next `open_here` turn off for videos of 20–30 minutes in the demo
snapshots (they show "Open original"). Acceptance 3 gains Ken Robinson's talk (`iG9CE55wbtY`,
1,204 s): `too_long` just over the cap, no model call.

**R4.5 Tests, named.** `tests/test_llm_transcribe.py`: `test_a_timeout_is_charged_its_estimate_
then_retried` replaced by `test_a_timeout_is_charged_once_and_not_retried` (one attempt, one
charge, `MediaTimeout`); `CLIP` and the parts test: a whole clip has `fps` and no offsets, an
offset clip keeps them, audio parts unchanged. `tests/test_transcript.py`: `plan_for` (YouTube
one window; audio unchanged; `plan_windows` tests stay). `tests/test_media_service.py`: a 1,190 s
video makes exactly one call over `[0, 1190]`; unknown language → one call, then `not_english`;
the ceiling allows two timed-out runs and refuses the third (`too_costly`); a 1,201 s video is
refused `too_long` at open with no model call. Router: 504 body on `MediaTimeout`.

**R4.6 Docs and the spend record.** DESIGN §21: one call per video, no offsets, the 20-minute
cap, the hang evidence. STATUS §4 deviations: offset windows dropped; video cap 30 → 20 min.
STATUS known issues: Vertex offset windows can hang with no error, cause unknown. Spend: the
failed runs cost **$0.229** of real Vertex money recorded in the *emulator* ledger only (the
production $8 guard never saw it): run 1 $0.121 (window 1 $0.049 + timeout $0.036 + cancel
$0.036), run 2 $0.072 (timeout + cancel), probe $0.035. The log's $0.193 was runs 1–2 only.

**Optional item taken as a stated risk:** `PendingDoc.windows` is keyed by index; an emulator
that still holds the old window "0" (0–600) would look complete under the one-window plan. The
re-run uses a fresh emulator and production has no media pending docs, so no code change.

## Round 4 review, round 2 (REVISE, 2 items; applied)
1. The fallback cap is **1000 s**, not 900 (R4.1 and the T04 comment): videos.list gives T01
   960 s, and a 900 s cap would refuse the acceptance video at open. The at-cap refusal case
   follows the cap (Ken Robinson, 1,204 s, is over both 1,200 and 1,000).
2. T04 is frozen by commit `7622bb7` ("media: freeze T04 before the whole-URL run"), made before
   any harness run touches it; "appended before any run of it" refers to that commit.
