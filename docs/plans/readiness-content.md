# Readiness from stored articles, plus two robustness fixes (decision 65)

Branch `oct16-seeding-2` (it already holds the S2 cached-recording check and `preingest_feed.py`,
committed with tests). Sourabh, 2026-10-15, after decision 64 left most demo rows without a
readiness line: "plan fix", then "yes" to the bigger fix with the politics/policy tweak folded in.
The code freeze is lifted again for this change only. Recording is Oct 16–17, submission by Oct 18.

**Cut-off:** checked on the clock at **19:00 IST Oct 15**: if R1/R2 are not merged by then, run the Oct 16 plan's S3 as planned
(same-image restart) and propose to Sourabh shipping B1/B2 alone and cutting R1/R2.

## Why rows are blank (measured 2026-10-15 on the re-seeded demo feeds, first pages)

Live: newcomer 4 of 11 rows without a line, trader 4 of 11, policy student 7 of 9. For every
blank row, the single words decision 64 rejected were listed: all but two were wrong senses
(Flow → Flow variable, horizon → Investment horizon, growth → On the up, Pip → Pip (finance),
basis → Basis (finance), short → Short positions). The two real ideas lost: Houthis [policy] on a
politics row, Autism [health] on a policy row. The rest name nothing in the graph in their title
and snippet (Albania protests, Pakistan politics, Kelly Clarkson). Title matching cannot recover
them; the article's own text can. S6 has since stored all 16 first-page articles (source `fetch`,
public library).

## Changes

**R1. Readiness from the article's verified ideas.** A feed row uses its article's **key ideas**
when all hold: `result.format == "article"`; a catalog doc (`app/content/catalog.py`) whose
`content_id == url_hash(result.url)` exactly (no index by `doc.url` or `final_url`); and
`is_corpus(doc)` (a reader's own `user_ingested` or extension page is private to them, DESIGN
§17.4). Key ideas: the doc's linked demands (`target_id` set and present in the served graph), one
per concept (its highest salience), the **K = 4 = READY_MAX** with the highest salience (ties by
first appearance). K equals READY_MAX so "stretch" on such a row comes only from a new prerequisite
(decision 60's meaningful reason), never from K itself. Decided now, not tuned after measuring.
- Changed for such a row: the readiness level, the read-first line and the "N ideas new to you"
  count in `why`, all from the key ideas. `read_first` excludes every idea the article itself
  links (all its linked target ids in the graph) plus its title concepts, so a prerequisite the
  article covers is never "read up on X first".
- Unchanged: the **ranking score** (its readiness factor and the goal boost still use title +
  snippet concepts, so R1 moves no row), topic relevance, and every video, podcast and unstored
  article (title rule).
- Code: `fr.FeedCandidate` gains `ideas: tuple[Concept, ...] | None = None` and `covered:
  frozenset[str] = frozenset()`; `fr.rank` uses ideas (when not None and non-empty) for level,
  read-first and the shown count, title concepts for the score. One pure helper in
  `recs/feed_rank.py`, `attach_ideas(candidates, docs_by_id, graph, k=READY_MAX)`, called from
  `recs/feed_router.get_feed`, `scripts/feed_quality.py` and `scripts/readiness_mix.py`, so the
  gates and live match. A stored doc with no linked demand in the graph keeps the title rule.
- `get_feed` gets docs from `await catalog.all_docs()`. On a cold instance that streams the
  `contents` collection once (≈ 330 docs); any exception there is logged and the feed falls back
  to the title rule (never fails). The live check records the first `/v1/feed` latency on the new
  revision.
- `RankedItem` and `FeedItemOut` gain `readiness_basis: "article" | "title"`; the web hover text
  (`apps/web/src/lib/readiness.ts`, ForYouTab chunk only, not the main bundle) is chosen by it:
  "Based on the main ideas in the article" / "Based on the ideas named in the title and summary".
  Web test; `make deploy-web` after the API on Sourabh's yes, with typecheck and the bundle check
  (main unchanged).
- DESIGN §17.2: readiness is "the article's key ideas when it is a public library article, else
  title and summary"; the "why" count and line use key ideas, the score's readiness factor and the
  goal boost use title concepts; the false-precision sentence and the hover text follow.

**R2. Policy and politics are neighbours for a plain single-word label.** F2's domain rule gains
one group beside the business group: (policy, politics). A plain label counts when the concept's
domain is the item's topic or both are in one group. This does change scores (a newly named idea
moves the readiness factor, goal boost and `keep_for`), so it is measured, not assumed neutral.

**B1. Read-time contention is retried.** `store/docstore.retry_contention` also retries
`google.api_core.exceptions.Aborted` (Firestore's cross-transaction contention raised during a
transaction's reads), with a fresh transaction each round; any other error is not retried. Seen
live once (2026-10-15 08:19:09 UTC, `/v1/explain` 500 while `warm_demo --shifts` sent 27 parallel
explains for one reader).

**B2. Deleting a reader retries once.** `FirestoreDocStore.delete_tree` retries the whole
recursive delete once (a new BulkWriter) when it raises; it raises if both fail. Seen live once
(08:19:30 UTC, `DELETE /v1/me` 500 "BulkWriter is closed…": a delete that failed against the
reader's in-flight writes was re-queued after the writer closed). The one leftover anonymous test
reader (Auth user and partial docs) is **not** hunted down: real demo visitors who never press
End demo leave anonymous users too, so it cannot be told apart safely without the uid salt. It is
recorded in STATUS §5 like the M6 leftover.

## Tests first

- `test_feed_readiness.py` (calls `reset_catalog()` where the catalog is used):
  - a stored corpus article's level and read-first come from its 4 key ideas (salience order, one
    per concept keeping the highest salience, a target not in the graph skipped) while its score
    equals the title-only score; `why` counts the key ideas; `readiness_basis` is "article";
  - a prerequisite the article links (its 6th idea) is not listed as read-first;
  - an unstored article, and a **stored video** whose hash matches, keep the title rule;
  - a `user_ingested` doc and an extension doc are ignored; a result URL with `utm_` parameters
    matches when the doc was stored under that exact URL (hash of the submitted string);
  - a stored doc with no linked demand in the graph, `ideas=()` and `ideas=None` keep the title rule.
- `test_feed_rank.py`: a policy label on a politics row counts and a politics label on a policy row
  counts; a policy label on a health row doesn't; a health label on a policy row doesn't.
- `test_feed_api.py`: the route attaches ideas from the catalog (a stored doc in the fake content
  store) and the item shows them with `readiness_basis`; a catalog that raises falls back to the
  title rule with the feed still 200.
- `test_docstore.py`: `retry_contention` retries `Aborted` raised during the body's reads with a
  new transaction each round and gives up after the rounds; other errors are not retried;
  `delete_tree` retries once after a raising first attempt (fake client) and raises if both fail.
- Web: `readiness.test.ts` hover text by basis (and the old text when the field is absent).

## Measurement (production, read only; recorded in STATUS §34)

`make check-gcp` first. `scripts/feed_quality.py` and `readiness_mix.py` use `attach_ideas`; the
"old" run is the branch's `feed_quality.py --title-only` (ideas off, R2 off), the "new" run without it:
- Per persona, first-page level mix and blank rows, old vs new; every read-first line on first
  pages listed and read.
- Selected URLs per persona, old vs new: differences may come only from R2 and each is listed. An
  article newly on a first page is pre-ingested before deploy within S6's caps (shared ingests
  left today: 15), or listed as ingesting live.
- Every single-word concept R2 newly names, on first pages and in the cached politics/policy
  `rec_cache` entries, listed and read for sense. One wrong sense means R2 is dropped, not tuned.
- **Gate before deploy (decision 60's stop rule):** one level on ≥ 80% of the newcomer's
  first-page rows, or a persona with no non-stretch article row → stop and tell Sourabh. Rows
  still blank are recorded, not tuned.

## Ship

API pytest + ruff; `pnpm -r typecheck`; web tests and bundle check. milestone-reviewer → PR → CI →
merge → `make deploy-api` then `make deploy-web` from clean `main`, each on **Sourabh's yes** → live:
a fresh demo reader per persona sees the measured mix (± a growth-related row), first `/v1/feed`
latency recorded, the Guardian video article's notes unchanged, `DELETE /v1/me` 204.

## Oct 16 plan amendments (`docs/plans/oct16.md`)

S3 is replaced by this deploy (a new image and digest, made after S5 and S6 finished), unless the
cut-off sends us back to S3 as planned. S4b, S7 (Guardian proposed: newcomer 10 notes, trader 4),
S8 for the two articles the 500 cut short, and S9 follow on the new revision.

Production writes: none for the fix beyond the deploys (and any extra pre-ingest the measurement
calls for, within S6's caps). Spend: $0 LLM.
