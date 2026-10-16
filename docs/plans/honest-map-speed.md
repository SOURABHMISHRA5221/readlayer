# Honest map, story Up next, faster first notes, fresh deploys (decision 69)

Sourabh, 2026-10-16 night, after trying a fresh account on the live site:
- Notes on a new link "still taking a lot of time" (a Guardian article: 55 s to notes).
- End-of-article Up next: "these suggestion should be on article content not on new terms as chips
  are already handling this" (every item said "Because ‘Attention deficit hyperactivity disorder’
  was new to you").
- The knowledge map: "i belive second screen news cards are still updating the knowledge?" and,
  on "Interest rates — can explain", "from where this is comming? is our delete data working
  correctly?". Checked read-only on his account: delete works (account created 18:08 UTC, no
  record older); 18 recorded ideas (6 Quick check answers, 12 home-country terms), nothing from
  screen 2's cards. Every other dot is a **prior guess** drawn exactly like evidence (finance θ = 0,
  yet "Interest rates" shows "can explain"). Asked hide or faint: **"yes"** to hiding guesses.
- The quick check showed "1 of 6" after the deploy: his browser ran the pre-deploy page (Firebase
  default `max-age=3600` on `index.html`). He said "yes" to taking all of these on together.
- After plan review, asked (1) may the story search send **library** article titles to the search
  providers, never pasted links, and (2) warm-up at startup (slower cold starts) or not: **"Go with
  what u feel is correct"** → (1) yes, corpus articles only (B); (2) no startup cost: warm in the
  background when a link is opened (C).

Decision 69 lifts the code freeze for this work (STATUS §10 row 69). Five parts, two PRs.
**PR 1** (`d69-speed`): E (hosting headers), C (warm on open, timing logs), D (linking effort, only
if its eval passes). **PR 2** (`d69-map-story`): A (map), F (wording, added Oct 17), B (story Up next) as two commits: B1 the
story basis with key ideas and library same_story/angle, B2 the story web search. Each PR: tests
first → milestone-reviewer → PR → CI → merge → `make deploy-api` (yes) → then `make deploy-web`
(yes) → live check.

**Schedule (Oct 17 IST).** PR 1 merged by 08:00. **Checkpoint 12:00**: PR 2 not harness-green → ask
Sourabh to cut, proposing B2 first (a revert of its commit), then F (its own commit), then A's
per-topic and goal views.
**Last feature deploy 18:00**; after it only the `/v2` removal ships (its own web deploy), then
gitleaks, the deck link and submit. The video is re-recorded after PR 2 is live (the map and Up next
are in the video line).

## What is wrong today (read from code and production logs)

- **Map** (`app/reader/overview.py`, `/v1/me/graph?view=overview`): solid = "current band ≥ heard
  of, edge with forgetting **else the prior**"; rings use the same p. With no edges, basic concepts
  (low `base_difficulty`) come out "understands"/"can explain" at θ = 0. When no domain qualifies,
  top-interest or business domains are shown "so the map is never empty". The per-topic and goal
  views (`app/me/router.py` `_band`, `knowledge_subgraph`) colour no-edge nodes from the prior too.
  The list view and profile counts (`_summary`) already use edges only.
- **End-of-article Up next** (`app/recs/router.py`, `basis="consumer"`): triggers are the spans
  scored new to this reader; reasons "Because ‘X’ was new to you" (`_why`, also for library primer
  items). The card chips (`basis="article"`, decision 67) use the article's key ideas, so both lists
  can be the same concept.
- **First notes on a fresh instance**: 25 analyses since Oct 14 — the first on an instance waits
  **11–17 s before its first model call**, later ones 0.1–0.3 s (LiteLLM imported on the first model
  call, `llm._litellm`; spaCy on first parse, 1.1 s logged). Separately, extraction → first embedding
  is ~1.8 s usually and ~12 s sometimes, also on warm instances; `llm embed` logs no latency or
  attempts, so the cause isn't known yet.
- **`link_confirm`** (MODEL_QUALITY, default thinking): 107 calls since Oct 13, median 4.9 s, **p90
  17.4 s, max 71.8 s**; output tokens p90 1992. The 55 s article had one 16.6 s call.
- **Hosting**: no Cache-Control on HTML, so Firebase serves `index.html` with `max-age=3600`.

## E. Fresh page after a deploy (PR 1, web config)

- `firebase.json`, both targets, rules that never overlap (Hosting regexes are RE2: no lookaround):
  `{"regex": "^/([^.]*|index\\.html|theme-init\\.js)$"}` → `Cache-Control: no-cache` (the app
  routes, `/`, and the one unhashed script in `apps/web/public/`); `/assets/**` → `public,
  max-age=31536000, immutable`; `/fonts/**` unchanged; security headers unchanged. The SPA rewrite becomes
  `{"regex": "^/[^.]*$", "destination": "/index.html"}` (every route in `lib/router.ts`
  `matchRoute` is dot-free; reader ids are `[A-Za-z0-9_-]+`), so `/assets/**` and other files are
  never rewritten and a missing old chunk is a 404, not `index.html` cached as immutable.
- Test (web): parses `firebase.json`; no `regex` anywhere in it (headers and rewrites) contains
  `(?=`, `(?!`, `(?<`; the rewrite applies to `/read/abc_-1`, `/welcome`, `/connect`, `/v2` and not
  to `/assets/x.js`, `/fonts/a.woff2`; header sample paths map correctly with the regex compiled as
  written (`/`, `/welcome`, `/read/abc`, `/theme-init.js` →
  no-cache; `/assets/x.js` → immutable; `/fonts/a.woff2` → its rule only); both targets equal.
- Acceptance: after `make deploy-web`, `curl -I` on `/`, `/welcome`, `/theme-init.js` and one
  `/assets/*.js` on both sites shows the new values; `/read/<a library id>` is 200 (the app); a
  missing `/assets/nope.js` is 404.

## C. Warm on open, and timing logs (PR 1, API)

- No change to startup (STATUS §5's choice stands: startup stays lean; min instances 1 during
  judging). Instead `llm.warm()`: a run-once sync function (`functools.lru_cache` behind a
  `threading.Lock`; imports LiteLLM via `_litellm()` and loads spaCy via `features._nlp()`; no
  model call, no spend), run with `asyncio.to_thread` as a task the caller keeps a reference to
  (no saved module-level task: tests use a new event loop each) and does **not** await, started at
  the beginning of phase 1 (`fetch_and_extract`, used by Open here
  and Read any link) and of `analyse_pending`. Phase 1 is mostly network (fetch 0.5–5 s), and the
  request holds CPU, so the import overlaps the fetch; the analyse request that follows finds it
  done or joins it. A warm failure logs a warning; the first model call then imports as today.
- Timing to find the remaining gap: `llm embed` logs `latency_ms` and `attempts`; `content ingested`
  logs `parse_ms`, `extract_ms`, `link_ms`, `grow_ms`. No behaviour change.
- Tests: an autouse fixture in `tests/conftest.py` replaces `llm.warm` with a no-op except in the
  warm-up's own tests (so ingest tests never import LiteLLM or fetch its cost map); `llm.warm()` runs
  once however often it's called and never calls a model (acompletion
  monkeypatched to fail if called; `LITELLM_LOCAL_MODEL_COST_MAP=True` set inside the test so it
  needs no network; production keeps the remote map, which the budget prices rely on); a warm
  failure is logged and swallowed; phase 1 and analyse start it; `lifespan` does not; the embed log carries latency and
  attempts; the ingest log has the four stage times.
- Acceptance (live, after deploy): the first analysis on a new instance waits < 2 s before its
  first model call (the log query in this plan); `startup_ms` and a cold `/health` on the new
  revision are within 10 % of 00038. One fresh link opened by a demo reader (writes: that article
  and its analysis, like any Read any link; the reader deleted). The embedding gap gets its own fix
  only once the new logs show its cause (not in this decision).

## D. Linking with low thinking, if the eval holds (PR 1, config)

- Fix first: `BuildCache._llm_key` keys answers by task, prompt version and prompt vars — not
  model or effort, so a run could replay old answers. Add the resolved model and, **only when an
  effort is set**, the effort. Test: a key with no effort equals a hard-coded key computed the old
  way (existing caches stay valid); a different effort or model → a different key.
- Run `evals.run --suite linker` twice on the same graph, each with a fresh cache directory:
  `--label d69-default` and, with `LLM_REASONING_EFFORT='{"link_confirm":"low"}'`, `--label
  d69-low`; both result files must show `cost_cached_usd == 0`; per-call latency recorded. Budget
  ≤ $0.40 (the Oct 10 fresh run cost $0.16).
- Ship rule (fixed before the runs): low ships only if variant precision ≥ default − 0.02 **and**
  link_confirm regression passes ≥ default's. Then `deploy.env.yaml` `LLM_REASONING_EFFORT` adds
  `"link_confirm": "low"` (ingest linking and concept growth). Otherwise nothing changes and STATUS
  records the numbers.

## A. The map shows only what we have evidence for (PR 2, API + web)

- `overview.build`: **solid** = concepts with an edge whose current band (edge with forgetting, its
  prior as the starting point as today) ≥ heard of; no edge → never solid. **Ready** rings: not
  solid, ≥ 1 prerequisite, every prerequisite **has an edge with p ≥ KNOWN_P** (any domain, not
  "in this domain's capped solid list"). Domains: evidence or chosen as today, but domains with no
  nodes are dropped **before** the `MAX_DOMAINS` cap; **no fallback** to top-interest or business
  domains — an empty map shows the existing "Read a few articles and your map fills in."
- Per-topic and **goal** views (`_band` in `/v1/me/graph`, incl. `exact`): a node with no edge gets
  band `unaware`, not a prior guess.
- `overview.p_know` stays prior-based: `/v1/me/bands` (the recap) uses it and is unchanged (test pins
  a no-edge concept's band).
- Web (`KnowledgeMap.tsx`, `profile.css`): topic and goal views add a legend entry "Nothing recorded
  yet" for hollow `unaware` dots, distinct from "Ready to learn". The inspector shows "Nothing
  recorded yet: read about it, or tell us below." only when `!ready && band === "unaware" &&
  recent.length === 0` (an edge with no evidence after a profile edit keeps today's text); "I know
  this / I don't" stay.
- Unchanged: scoring and notes still use the prior (DESIGN §5); the profile summary and list;
  demo personas (edges from their templates).
- Tests (API): fresh reader (θ only, no edges) → no nodes; home-term edges → solid in their domains,
  nothing else; a ring only when its prerequisites have evidence, including a prerequisite in
  another domain; a chosen domain without evidence takes no slot; per-topic and goal views: no-edge
  node `unaware`, edge node keeps its band; `/me/bands` unchanged. Personas (local graph): every
  solid node has an edge and each persona keeps ≥ 12 solid (measured: newcomer 31, trader 16,
  policy_student 27 recorded among today's solid). Web: legend entry in topic view; inspector text
  rule (three cases); empty state.
- Harness: fresh account (Software + India + Sports, Quick check answered) → only home terms, Quick
  check terms and rings; a persona's map; a goal view; axe 0 at 1440/390, light/dark.

### A2. A topic level only when the level was set or moved (added 2026-10-17, found on the harness)
The d69 harness (fresh account, Software + India + Sports) showed the profile saying "Comfortable in
business, economics, finance, policy, sports and technology": the 12 India home terms put edges in
four domains, and `GET /v1/me/profile` counted a domain with any edge as `rated`, so its untouched
θ 0 read "comfortable" (the summary and the level cards) — the same guess-as-fact as the map. Now
`rated` = a comfort answer or |θ| > 0 (the field, reading's Elo, Quick check answers, profile
edits); recorded ideas alone don't rate a domain. The web already shows "Not rated yet" and keeps
the "N ideas you've shown you know" count. Test: home terms alone → those domains unrated and absent
from the summary; the field's domain rated. Demo personas are unaffected (their θ is set).

## B. End-of-article Up next follows the article (PR 2, API + web)

- New `basis="story"` on `GET /v1/content/{id}/recommendations`; the web's end-of-article list
  switches to it. `basis="consumer"` stays unchanged for the live old web during the deploy.
- **B1 (commit 1)**: triggers are the article's key ideas (as `article`); library `same_story` and
  `angle` candidates keep their reasons; every other item gets `_key_idea_why` ("On ‘X’, a key
  idea here"), library primer and deeper included — no "was new to you" on this basis.
- **B2 (commit 2), story search, corpus articles only** (`is_corpus(doc)`; never `user_ingested`
  or `extension` docs — DESIGN §16.3 and the `web_search` docstring amended to this narrower rule,
  with Sourabh's answer above). A news search with the article's **title** (cleaned like
  `build_query`, ≤ 120 chars) for `article` (Tavily, `news=True`) and `video` (YouTube), started in
  the background like `refresh` and tracked in flight under `(f"story:{content_id}", fmt)`; a
  stored entry (even empty) means no new search ever (`cached_entry`, no expiry); failures aren't
  stored, in-flight tracking stops immediate repeats. Its own counter `story` and
  `STORY_SEARCH_DAILY_CAP` (default 40); counts against the global, YouTube and anonymous caps,
  never `FEED`; anonymous readers only while the anonymous allowance lasts. Results: not the
  article's own URL (`url_hash` of `doc.url` and `doc.final_url`) and must mention one of the top 3
  key idea labels or share ≥ 2 distinctive title words (stopwords out). Reason "More on this story".
- Order: after `select`, up to 2 story items lead, then the rest in score order. `pending` while a
  story search runs.
- Pasted links (like Sourabh's Guardian link) get B1 only: key ideas and library items.
- Tests: B1 — key-idea reasons on every non-story item incl. a library primer; same_story/angle
  reasons kept; `consumer` unchanged. B2 — story items lead with "More on this story"; own URL
  dropped by hash; unrelated results filtered; `user_ingested` and `extension` docs make no provider
  call; story search leaves the `FEED` count unchanged and raises `anonymous` for an anonymous
  reader; story cap reached → key ideas only; two concurrent requests → one provider call per
  format; a second view after an empty result → no call; pending while running. Web: the end list
  asks `basis=story`.
- Harness: open a library article → story items first, then key ideas; no "new to you".

## G. Screen 2: an equal mix of the chosen formats (added 2026-10-17)

Sourabh, 2026-10-17: "onboarding second step me bhi full read read read hai we need to change that
so that the content that is suggested is an equal mix if in the previous step i select podcast and
reading". Cause: `feed_rank.onboarding_mix` (decision 68 F4) put articles first within each topic
and guaranteed only 2 of each chosen video/podcast format, so Read + Listen gave ~6 articles, 2
podcasts, 1 video. Now `onboarding_targets`: every format not chosen gets 1 card; the chosen ones
(articles when none) share the rest equally (remainder in article → video → podcast order): Read +
Listen of 9 → 4 articles, 4 podcasts, 1 video; one chosen → 7 + 1 + 1; all three → 3 / 3 / 3. A
chosen format short of results is made up by the other chosen ones first. New cards take turns by
chosen format (topics interleaved within each), the other formats after; served cards keep their
slots and pending searches still hold slots for a short format (both as before). Tests: the shares
above, the turns, topics interleaved within a format, a short chosen format made up; decision 68's
served/pending/default tests unchanged and passing. Harness (`tools/shots/d69_mix.py`, Read +
Listen, three topics): 4 / 4 / 1 in turns. Pure function, no new searches or cost.

## F. "Consume", not "read" (PR 2, its own commit; added 2026-10-17)

Sourabh, 2026-10-17: "on landing and everywhere we mentioning read a lot so change it to
"consume content" everywhere posible cus or goal is not only read". Rule: where "read" means what
the consumer does in general, say **consume / consume content**; where that reads badly, a
format-neutral word (open, learn, explore, based). **Kept**, because "read" is literally right or
fixed: article format words (Read / Watch / Listen, "I'd read this", "min read", "Read with notes",
"Read next" on an article, "Read the explainer", "Before you read" — a set with "Before you watch /
listen", also the annotator's and extension's pre-read); Gloss itself reading a page ("Reading the
article and preparing your notes…", the extension's "Gloss doesn't read mail…"); the privacy page's
"words read" count; the readiness idiom "A stretch: read up on X first" (in the landing screenshot
and README image, no time to recapture before 18:00); the consent text "Gloss may keep what I read
and answer here" (`consent-v2`, tied to a recorded version); `/read/` URLs and code. The extension
is unchanged (its strings are about Gloss reading a page; changing it needs a new release); `/v2` is
skipped (removed before submission). Plan-reviewer round 1: REVISE 12, applied here.

Changes:
- **Landing** (`LandingPage.tsx`, `Hero.tsx`, `Extension.tsx`, `formatsFull.ts`, `WatchListen.tsx`):
  "Read anything. Understand all of it." → "Consume anything. Understand all of it." (+ page title);
  "Read as:" → "View as:"; "Read with Gloss:" → "Open with Gloss:"; "fills in as you read" → "as you
  consume content"; "the notes thin out as you read more" → "as you consume more"; "Everyone reads
  past something." → "Everyone misses something."; "Gloss reads with you." → "Gloss follows along
  with you."; "What you can read" → "What you can open"; "Your reading stays yours" → "What you
  consume stays yours"; "what you've read" → "what you've consumed"; "a reading level" → "a knowledge
  level"; "Reading the news somewhere else?" → "Following the news somewhere else?"; "into Read any
  link" (both) → "into Open any link".
- **Static HTML** (`apps/web/index.html`): regenerate the pre-rendered hero (`UPDATE_HERO=1` on
  `test/landingHero.test.ts`); hand-edit `<meta name="description">` and `og:description`
  ("read anything, understand it your way" → "consume anything, understand it your way").
- **App**: "Read any link" (top bar, sidebar, button "Read") → "Open any link" / "Open"; library
  title "Read anything. Understand it your way." → "Consume anything. …"; "Paste any link to read it
  here." → "to open it here"; "Your reading profile" (title, eyebrow, account menu) → "Your profile";
  persona picker "Reading as" / "Read as" → "Viewing as" / "View as"; "reading goals" → "goals";
  goal habit "Read a little every week" → "Learn a little every week"; "Learning is paused, so
  reading isn't counting." → "so nothing you consume counts"; "reading doesn't / won't change your
  profile" → "what you consume doesn't / won't …"; "Where do you read from?" → "Where are you
  based?" (onboarding, profile); "What do you want to read about?" → "What do you want to learn
  about?"; "Tell me what you'd read." → "Tell me what you'd open."; the "Start reading" button →
  "Start exploring"; "You can start reading anyway." → "You can start anyway."; the discover card's
  aria-label "Would you read “…”?" → by format ("Would you watch …", from `FORMAT_VERB`); "fills in /
  updates as you read" (map, week panel, recap, feed) → "as you consume content"; "Read a few
  articles and your map fills in." → "Consume a few pieces and your map fills in."; "Sign in again
  to keep reading." → "to keep going"; "plenty more to read" → "plenty more to consume"; evidence
  "Common where you read from" → "Common where you're based", "Reading activity" → "Activity";
  persona blurb "Reads central banks…" → "Follows central banks…"; Connect "Notes on any article you
  read" → "you open"; progress aria "Reading progress" → "Progress"; map inspector "read about it" →
  "explore it", "not from reading yet" → "not from anything you've opened yet"; privacy: "Your
  reading" → "What you consume", "Reading events" → "Activity events", "Reading goals" → "Goals", "a
  reading level" → "a knowledge level", "cleared when you start reading" → "when you finish setting
  up", "what else you've read" → "what else you've opened"; the `QuickCheck.tsx` comment.
- **API**: `ingest/router.py` "Open it in Gloss with Read any link." → "… with Open any link."
  (shown by the extension); `media/refusals.py` "Live streams can't be read in Gloss." → "can't be
  opened in Gloss".
- **README**: line 8 (heading), 65 ("reading profile", "reading goals"), 67 ("Read any link, any
  format"), 202 ("reading-profile summary"), 40 / 70 / 226 ("reading history" → "what they
  consume"). Kept: 66 (the readiness quote, kept idiom), 68 "deeper reads", the extension lines,
  the milestone history, image alts.
- **Guard** (`test/wording.test.ts`, describe line names decisions 67 and 69 F): whitespace
  normalised before matching (`value.replace(/\s+/g, " ")`); also bans `\breading\b`, `\bas you
  read\b`, `\bread anything\b`, `\bread any link\b`, `\bread from\b`, `\breading goals\b`,
  `\byou(?:'ve|'d)? read\b`; kept lines carry `// wording-ok: <reason>` (`ReaderPage.tsx` "Reading
  the article…", `preread.ts`'s heading if walked, the consent line, the readiness idiom if hit);
  a check that `index.html` doesn't match `/read anything/i`.
- **Tests and harness updated**: `wideLayout.test.tsx` (106, 113, 115, 171), `profileFormat.test.ts`
  (9), `honestMap.test.tsx`, `welcome.test.tsx` (205), `landingV2.test.tsx` (146),
  `landingHero.test.ts` (regenerated); harness `click_text("button", "Start reading")` in
  `tools/shots/d48.py`, `d50.py`, `onboarding.py`, `m8.py` → "Start exploring".
- **Records**: DESIGN's "Read any link" mentions and a UI wording note; STATUS row 69 note with the
  quote; `docs/recording.md`; a reminder to update the deck and submission text (tagline, "Open any
  link").
- Harness: landing, library, onboarding, profile axe 0 at 1440/390 after the change.

## Live acceptance after PR 2 (production writes listed)
- Read-only `GET /v1/me/graph?view=overview` on Sourabh's account: no "Interest rates"; every solid
  node has `recent`.
- One demo persona's overview live: ≥ 12 solid nodes.
- One library article opened as a persona: "More on this story" items and key-idea reasons, no
  "new to you"; `ops/search` today rises by ≤ 3 calls (1 Tavily + 1 YouTube = 2 units).
- Writes: ≤ 2 `rec_cache` `story:*` entries per opened corpus article; the persona session (deleted).

## Docs and records
STATUS §10 row 69 (quotes above; the freeze lifted), §9 rows (schedule above), §37 acceptance;
DESIGN §15.1 (map), §8 (`basis`), §16.3 (story search rule), the effort table; AUTOPILOT_LOG.
Commits `M69: …` per PR.
