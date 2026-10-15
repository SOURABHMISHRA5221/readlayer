# Feed quality fix (decision 64)

Branch `oct16-seeding` (the seeding work found it; one PR for both). Sourabh, 2026-10-15, on the
wrong For you rows found while gating the re-seeded demo feeds: "fix if you need deadline will
extend by 4 days minimum but still fix". So the code freeze is lifted **for this fix only**, and
the submission date moves by ≥ 4 days (exact date from Sourabh). The Oct 16 seeding plan
(`docs/plans/oct16.md`) pauses after S4 and resumes on the fixed feeds (§ "Then").

## What is wrong (measured 2026-10-15 on the three re-seeded `persona_feeds`, served graph
`2026-10-10-folded-5206+g1`, 5,288 concepts)

`fr.named_concepts` scans each item's title + snippet for 1–4-word n-grams that equal a concept
label **or alias** (`graph.lookup`). Its results drive the readiness level, the "read first" line,
the ranking (`readiness(len(new))`) and, for searched items, topic relevance (`is_relevant`).

1. **Stopword aliases.** The alias index holds `it` → Give the treatment (sports), `to` → Take a
   touch (sports), `at` (from `AT`) → Activity theory (education). "to" is in nearly every
   snippet, so almost every row names a sports concept.
2. **Ambiguous single words.** One plain word matches a concept in another sense: `stocks` →
   Stock variable (whose prerequisite gives "read up on Economic stocks and flows" on three
   stock-market videos), `flows`/"Flow" → Flow variable, `futures` → Futures contract
   ("Derivative contracts" on "Gadgets of the future"), `basis` → Basis (finance) ("Spread, Basis
   points" on a hospital-staffing story), `short` → Short positions ("Leverage" on a policy
   podcast), `reserves` → Bank reserves (on a musical), `coverage`, `models`, `benefits`,
   `pip` → Pip (finance). Of 3,656 aliases, 798 are single words.
3. **Script filter.** `mostly_latin` passes "ഈ റാലി സൂചനയോ| Political Analysis|Debate Malayalam…"
   (most letters are Latin). Latin-script Hindi ("Nifty Crash 2026: SIP Band Karein…") cannot be
   caught from the title at all.
4. **Non-news sections.** The Guardian's `world` feed (politics topic) carries
   `/stage/2026/oct/15/paddington-the-musical…`, served as politics.

Not affected: article notes. `graph/linking.py` looks up only demand labels and anchors the model
already extracted, then confirms with `link_confirm`. The other `lookup` callers (onboarding text,
goals, resolve) match a whole short phrase the reader typed; fix 1 covers their only exposure.

## Changes (pure, deterministic, no LLM, no new keyword list beyond stopwords)

**F1. No stopword keys in the alias index** (`graph/graph.py` `alias_index`): an alias whose
normalised key is a single English stopword (`a an the to it at in on of or and as is be by for
if no not so up us we do go me my am are was has had this that with from`, a constant next to the
index) is not indexed. Labels are untouched. This is a guard in code, so online growth can't
re-add one; the graph file in Cloud Storage is not rewritten.

**F2. Free-text matching takes only unambiguous single words** (`recs/feed_rank.py`
`named_concepts`). Multi-word matches are unchanged. A **single-word** match counts only if:
- it equals the concept's **label** (normalised) and the label has no parenthetical
  disambiguator ("Basis (finance)", "Pip (finance)" are ambiguous by their own name); or
- the concept's label or alias is an **acronym** (all caps, 2–5 characters, e.g. RBI, SEBI, AI,
  GDP) **and** the source token is written in capitals too ("AT" yes, "at" no).
Single-word **aliases** in lower case (stocks, flows, futures, coverage, models, benefits,
reserves, short, liquidity, maturity) no longer count in free text. A skipped word does not
consume the position, so a longer match starting there is still tried first (already the order).
`named_concepts` keeps its signature; callers (feed, snapshot, onboarding feed) get the fix.

**F3. Script filter** (`recs/feed_rank.py` `mostly_latin` → `is_latin_title`): a title with
**two or more letters outside Latin script** is rejected (Latin-1 and Latin Extended stay
allowed: "café", "Müller"; symbols like ₹ and emoji are not letters). Used by `is_feed_page` and
`outlet_items` as today.

**F4. Spoken language for videos** (`recs/web_search.py`, YouTube provider): `videos.list` asks
for `part=snippet,contentDetails` (same 1-unit quota as today) and drops a video whose
`defaultAudioLanguage` (or, if absent, `defaultLanguage`) is set and doesn't start with `en`. A
video with neither set is kept (no evidence). Applies to the feed and Up next alike (both lead to
English explanations).

**F5. Non-news sections in outlet feeds** (`recs/outlet_feed.py` `outlet_items`, given the topic):
an entry whose URL path has a segment in `NON_NEWS_SEGMENTS` (`stage, film, music, books,
tv-and-radio, artanddesign, lifeandstyle, fashion, food, travel, games, crosswords,
entertainment`) is dropped unless the topic is `culture`; one with `sport` is dropped unless the
topic is `sports`. `topic_items` passes the topic through.

## Tests first (red, then green)

- `test_graph.py`: an alias `it`/`to`/`AT` is not looked up; a label "To" (none exist; synthetic)
  still is; a multi-word alias containing stopwords ("Bank of England") still is.
- `test_feed_rank.py` `named_concepts`, on a synthetic graph with the live shapes: "chip stocks
  tumble" → no Stock variable; "Stock market today" → Stock market; "gadgets of the future" →
  nothing; "futures contract prices" → Futures contract; "working arrangement basis" → nothing;
  "RBI raises the repo rate" → RBI, Repo rate; "at the RBI" → no Activity theory; "AT&T"-style
  caps acronym match; "Inflation rises" → Inflation (single-word label).
- `test_feed_rank.py` `is_latin_title`: the Malayalam title rejected; "Müller's café" kept; "₹21,000
  off 🔴" kept; one stray non-Latin letter kept.
- `test_outlets.py`: a Guardian `/stage/` entry dropped from politics, kept for culture; `/sport/`
  kept for sports only.
- `test_recs_web.py` (YouTube transport mock): `defaultAudioLanguage` `ml`/`hi` dropped, `en-GB`
  kept, missing both kept; the request asks for `snippet,contentDetails`.

## Measurement (before/after, recorded in STATUS §33)

A read-only script, `scripts/feed_quality.py`: over the three stored `persona_feeds` (and the For
you `rec_cache` entries of the last 3 days, if present), per row the named concepts and read-first
line under the served graph, printed for old and new code side by side; totals: rows naming a
sports/education concept on a non-sports/education topic, rows with a read-first line, rows
whose read-first line comes from a single-word match. Targets: **0** rows naming Take a touch /
Give the treatment / Activity theory; **none** of the four named wrong read-first lines; the
legitimate matches above (RBI, SEBI, Repo rate, Inflation, Insider trading, Stock market,
Commodity Futures Trading Commission) still found. Readiness mix after (stop rule as before). I
read every first-page row of the three personas and record any that is still wrong.

## Ship

Suites: API pytest + ruff, `pnpm -r typecheck` (no web change expected). milestone-reviewer → PR
→ CI → merge → `make deploy-api` from clean `main` on **Sourabh's yes** (a code change, so a
build, not a same-image revision) → live check: `GET /v1/feed` as a fresh demo reader per persona
shows no wrong line from the list; a signed-in feed refresh still returns rows.

## Then (the Oct 16 plan resumes)

On UTC Oct 16 (today's YouTube results are cached per day and predate F4): `seed_demo_feed`
dry run + real (S2 again, ≤ 24 searches, Tavily 324 left), S4 gate, then S5, S6 (its UTC-day rule
moves with it: S6 runs a UTC day before the video), S3 (the deploy above already restarted
instances, but S5/S6 come after it, so the same-image restart stays), S4b, S7–S9. The plan's
dates shift with the deadline; nothing else in it changes.

Production writes: none for the fix itself (code + one deploy). Spend: $0 LLM; one Cloud Build.
