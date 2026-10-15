# Feed quality fix (decision 64)

Branch `oct16-seeding` (the seeding work found it; one PR for both). Sourabh, 2026-10-15, on the
wrong For you rows found while gating the re-seeded demo feeds: "fix if you need deadline will
extend by 4 days minimum but still fix". So the code freeze is lifted **for this fix only**, and
the hackathon deadline has ≥ 4 days of slack, but the plan stays: submit by Oct 18 (Sourabh,
2026-10-15: "we will not change date yet as our plan will be to submit by 18th only"). The Oct 16 seeding plan
(`docs/plans/oct16.md`) pauses after its S4 gate and resumes on the fixed feeds (§ "Then").

## What is wrong (measured 2026-10-15 on the three re-seeded `persona_feeds`, served graph
`2026-10-10-folded-5206+g1`, 5,288 concepts)

`fr.named_concepts` scans each item's title + snippet for 1–4-word n-grams that equal a concept
label **or alias** (`graph.lookup`). Its results drive the readiness level, the "read first" line,
the ranking (`readiness(len(new))`) and, for searched items, topic relevance (`is_relevant` via
`feed.keep_for`).

1. **Stopword aliases.** The alias index holds `it` → Give the treatment (sports), `to` → Take a
   touch (sports), `at` (from `AT`) → Activity theory (education). "to" is in nearly every
   snippet, so almost every row names a sports concept.
2. **Ambiguous single words.** One plain word matches a concept in another sense: `stocks` →
   Stock variable (whose prerequisite gives "read up on Economic stocks and flows" on three
   stock-market videos), `flows`/"Flow" → Flow variable, `futures` → Futures contract
   ("Derivative contracts" on "Gadgets of the future"), `basis` → Basis (finance) ("Spread, Basis
   points" on a hospital-staffing story), `short` → Short positions ("Leverage" on a policy
   podcast), `reserves` → Bank reserves (on a musical), `coverage`, `models`, `benefits`,
   `pip` → Pip (finance). Of 3,656 aliases, 798 are single words. Plain single-word labels have
   the same risk in other senses (Spread, Administration, Options, Correction, Margins, Default,
   Commission…), and all-caps labels match lower-case words (`cafe` → CAFE, `ram` → RAM).
3. **Script filter.** `mostly_latin` passes "ഈ റാലി സൂചനയോ| Political Analysis|Debate Malayalam…"
   (most letters are Latin). Latin-script Hindi ("Nifty Crash 2026: SIP Band Karein…") cannot be
   caught from the title at all.
4. **Non-news sections.** The Guardian's `world` feed (politics topic) carries
   `/stage/2026/oct/15/paddington-the-musical…`, served as politics. Stored outlet lists keep
   previous items up to 3 days (`outlet_feed.merge`) without re-filtering, and `seed_demo_feed`
   reads them through `feed.outlet_candidates`, so a collection-time filter alone would not
   remove it before Oct 18.

Article notes: `graph/linking.py` looks up only demand labels and anchors the model already
extracted, then confirms with `link_confirm`. F1 changes it only for the dropped stopword keys: an
anchor that is exactly one of them now goes to embeddings plus `link_confirm` instead of an exact
hit. `reader/onboarding_text.word_topic` scans 1–2-word chunks of typed text; F1 only removes hits
there and `_keep` already filters these stopwords. Goals and resolve match whole typed phrases.

## Changes (pure, deterministic, no LLM, no new keyword list beyond stopwords and sections)

**F1. No stopword keys in the alias index** (`graph/graph.py` `alias_index`): an alias whose
normalised key is a single English stopword (`a an the to it at in on of or and as is be by for
if no not so up us we do go me my am are was has had this that with from`, a constant next to the
index) is not indexed (a comment says it differs on purpose from `reader/onboarding_text.STOP_WORDS`,
 which serves a different filter). Labels are untouched. A guard in code, so online growth can't re-add one;
the graph file in Cloud Storage is not rewritten. The measurement prints every alias F1 drops
from the served graph (alias, concept, domain) into STATUS §33.

**F2. Free-text matching takes only unambiguous single words** (`recs/feed_rank.py`
`named_concepts(graph, text, topic)`). Multi-word matches are unchanged. A **single-word** match
counts only if one of these holds, decided now and not tuned after measuring:
- **Acronym:** the concept's label or matched alias is all caps (≥ 2 letters, possibly with
  digits or `&`: RBI, SEBI, GDP, VAR, M&A, G20, EBITDAR, Q1FY27), **and** the source token is
  written in caps too. A caps-only name of any length keeps the caps-token requirement.
  An all-caps label never matches a lower-case or title-case word ("cafe" ≠ CAFE, "Ram" ≠ RAM).
  Accepted and recorded loss: in an all-caps title ("WHAT'S AT STAKE FOR RAM PRICES") every word
  is in caps, so RAM still matches; F1 already removes AT.
- **Plain label:** the word equals the concept's label (normalised), the label has no
  parenthetical disambiguator ("Basis (finance)", "Pip (finance)" are ambiguous by their own
  name), **and** the concept's domain is the item's topic, or both are in `BUSINESS_DOMAINS`
  (`graph/taxonomy.py`: economics, finance, business, policy). So "Inflation" counts on an
  economics row and not on a sports row; "Spread" (finance) counts on a policy row (policy is in
  the group) but not on a health or politics row. Business-group cross-matches that are wrong
  show up in the measurement's single-word list and are recorded, not tuned.
Single-word **aliases** in lower case (stocks, flows, futures, coverage, models, benefits,
reserves, short, liquidity, maturity) no longer count in free text. Every caller passes the topic
it already has: `feed.keep_for`, the two `FeedCandidate` builders in `feed.py` (fresh results and
`snapshot_candidates`), `outlet_candidates`, and `me/onboarding_flow.py`. `keep_for_concept`
(Up next for a concept) is unchanged: it names its concept's own label and aliases.

**F3. Script filter** (`recs/feed_rank.py`: `mostly_latin` renamed `is_latin_title`): a title with
**two or more letters outside Latin script** is rejected (Latin-1 and Latin Extended stay allowed:
"café", "Müller"; symbols like ₹ and emoji are not letters). Callers: `is_feed_page`,
`outlet_items`, and `media/sources.py` (lines 100 and 168, the `not_english` refusal when a video
or podcast is opened), so media refuses a mixed-script title too. Applied at read time as well
(F5).

**F4. Spoken language for videos** (`recs/web_search.py`, YouTube provider): `videos.list` asks
for `part=snippet,contentDetails` (same 1-unit quota as today) and drops a video whose
`defaultAudioLanguage` (or, if absent, `defaultLanguage`) is set and doesn't start with `en`. A
video with neither set is kept (no evidence). Applies to the feed and Up next alike (both lead to
English explanations). `CACHE_VERSION` is **not** bumped: today's cached feed and Up next entries
keep their results until the UTC day changes or their TTL ends; new searches get F4.

**F5. Non-news sections** (`recs/outlet_feed.py`): `outlet_items(outlet, entries, now, topic)`
drops an entry whose URL path has a segment in `NON_NEWS_SEGMENTS` (`stage, film, music, books,
tv-and-radio, artanddesign, lifeandstyle, fashion, food, travel, games, crosswords,
entertainment`) unless the topic is `culture`, and one with `sport` unless the topic is `sports`.
Callers: `outlet_job.topic_items` (passes the topic) and `scripts/check_outlets.py`. **Also at read
time**: `feed.outlet_candidates` applies the same section check and F3 to stored items, so
previous lists kept by `merge` are cleaned without waiting 3 days. `snapshot_candidates` filters
nothing at serve time (unchanged), so the live demo feed keeps Paddington and the Malayalam video
until the re-seed; the "Ship" live check covers read-first lines only, and the off-topic check is
the S4 gate after the re-seed.

## Tests first (red, then green)

Existing 2-argument `named_concepts` calls updated first: `tests/test_feed_rank.py`,
`tests/test_feed_readiness.py`, `scripts/readiness_mix.py` (and any other `rg named_concepts` hit).

- `test_graph.py`: aliases `it`, `to`, `AT` are not looked up; a synthetic label "To" still is; a
  multi-word alias with stopwords ("Bank of England") still is.
- `test_feed_rank.py` `named_concepts`, on a synthetic graph with the live shapes (Stock variable
  with alias `stocks`, Stock market, Futures contract with alias `futures`, Basis (finance), RBI,
  Repo rate, GDP, M&A, CAFE, Inflation [economics], Spread [finance], Take a touch with alias `to`):
  "chip stocks tumble" → no Stock variable; "Stock market today" → Stock market; "gadgets of the
  future" → nothing; "futures contract prices" → Futures contract; "working arrangement basis" →
  nothing; "RBI raises the repo rate" → RBI, Repo rate; "at the RBI" → RBI only; "rbi" lower case →
  nothing; "M&A deals" and "GDP growth" → M&A, GDP; "EBITDAR margin" → EBITDAR, "ebitdar" →
  nothing; "cafe owners" → no CAFE; "Inflation rises" on
  an economics row → Inflation, on a sports row → nothing; "virus spread" on a health row →
  nothing, on a finance row → Spread.
- `test_feed_rank.py` `is_latin_title`: the Malayalam title rejected; "Müller's café" kept; "₹21,000
  off 🔴" kept; one stray non-Latin letter kept.
- `test_media_sources.py`: a mixed-script title refused `not_english`.
- `test_outlets.py`: a Guardian `/stage/` entry dropped from politics by `outlet_items`, kept for
  culture; `/sport/` kept for sports only; a stored `/stage/` item in an `OutletList` is not a
  politics candidate of `outlet_candidates`, nor a stored mixed-script title.
- `test_recs_web.py` (YouTube transport mock): `defaultAudioLanguage` `ml`/`hi` dropped, `en-GB`
  kept, missing both kept; the request asks for `snippet,contentDetails`.

## Measurement (before/after, recorded in STATUS §33)

`make check-gcp` first. Old code from a `git worktree` of `main` with the branch's
`scripts/feed_quality.py` copied into it (uncommitted there); new code from the branch. A
read-only script, `scripts/feed_quality.py`, run once under each (output diffed):
- Over the three stored `persona_feeds`: per first-page row the named concepts, readiness and
  read-first line; totals of rows naming Take a touch / Give the treatment / Activity theory, rows
  with a read-first line, and **every single-word-label match** on first-page rows, listed.
- Relevance: per persona topic, how many `feed:`/`feedx:` `rec_cache` results from the last 3 days
  pass `keep_for`, and how many snapshot items would now fail `is_relevant`. **Floor set now:**
  every persona topic keeps ≥ 2 videos and ≥ 2 articles where it had them before; a topic below
  the floor is reported to Sourabh, not tuned.
- The F1 drop list (alias, concept, domain).
Targets: **0** rows naming the three junk concepts; **none** of the four named wrong read-first
lines; RBI, SEBI, Repo rate, Inflation, Insider trading, Stock market and Commodity Futures
Trading Commission still found. Single-word-label matches that are still wrong are recorded as
known issues (STATUS §5), not tuned.

## Docs

DESIGN §17.1 (English check: the two-letter rule; relevance example "names a penalty" now holds
through a label in the topic's domain or an acronym), §17.1a (collection drops non-news sections
and mixed-script titles, also at read time), §17.2 (readiness match rule). STATUS §10 decision 64;
§5 close the "Telugu title passed the 70% check" row and add any recorded losses; §9 dates when
Sourabh gives them; §33 acceptance.

## Ship

Suites: API pytest + ruff, `pnpm -r typecheck` (no web change expected). milestone-reviewer → PR
→ CI → merge → `make deploy-api` from clean `main` on **Sourabh's yes** (a code change, so a
build) → live check: `GET /v1/feed` as a fresh demo reader per persona shows none of the four
wrong read-first lines and no junk-concept row; a signed-in feed refresh still returns rows.

## Then (the Oct 16 plan resumes)

On UTC Oct 16 (today's search results stay cached under the old filter until the day changes):
`seed_demo_feed` dry run + real (S2 again, ≤ 24 searches; Tavily ≈ 318 left after the first S2,
which used 6 credits). The dry run is also the **article floor** check after F5 (≥ 2 readable
articles per topic; the measurement had no `feedx:` entries, so it counted videos and podcasts
only). S4 gate (now also: read every row; no off-topic outlet item; any non-English video left goes
to STATUS §5 as a known issue, not into tuning; **count rows with no readiness line per persona**:
if a persona's page is still mostly line-less, tell Sourabh, no tuning), then S5, S6 (runs a UTC day before the video), S3, S4b, S7–S9. S4b also
checks the landing still's line "A stretch: read up on Income distribution first" under the new
code; if the row no longer gets it, re-shoot the still or record the mismatch in STATUS §5.

Production writes: none for the fix itself (code + one deploy). Spend: $0 LLM, no searches, one
Cloud Build.
