# Oct 16 seeding plan (BUILD_PLAN M9 prompt tail, STATUS §9 "Oct 16", M9 plan T14)

Branch `oct16-seeding`. Code freeze: **no product code changes** (`apps/*/src`, `apps/api/app`).
One new operational script is allowed (`apps/api/scripts/preingest_feed.py`, S6), so the
milestone-reviewer can see everything that wrote production. Everything else here is data in
production plus docs. Started 2026-10-15 (07:18 UTC) at Sourabh's request ("resume with the Oct 16
items, starting with the persona re-seed"). Video and deck are Sourabh's by hand (BUILD_PLAN "You
do by hand"); this plan ends with the facts he needs for them (S9).

**Pre-step for every local script** (S1, S2, S4, S5, S6): `make check-gcp` (account
`sourabhlocalllm@…`, project `readlayer-sourabh-26`; stop on a mismatch); `FIRESTORE_EMULATOR_HOST`
unset; `GOOGLE_APPLICATION_CREDENTIALS` is the readlayer ADC file, not the shell's default key;
and `get_settings().db_project` printed and equal to `readlayer-sourabh-26`. Only `ingest_media.py`
prints its own target; the others print nothing about Firestore, so this check is the guard.

## What was measured before writing this (2026-10-15, read only)

- `seed_personas` dry run against `CONCEPTS_URI` (graph `2026-10-10-folded-5206`): newcomer 109
  edges, trader 86, policy student 115; 1.4–1.9% of the 1 MiB doc limit; no missing anchors.
- Stored `persona_templates/*`: `graph_version 2026-10-04`, created 2026-10-05.
- Field-by-field diff, fresh build vs stored: **same concepts, same bands, same θ, same evidence
  weights**. Only `version`, `graph_version` and the seed timestamps (evidence `at`, `last_seen`)
  differ. So the re-seed changes no note choice by itself; it resets the forgetting clock
  (`reader/model.py` `forget`, 90-day half-life on `last_seen`): seeded knowledge copied today is
  at λ ≈ 0.93 of its seeded strength (10 days), ≈ 0.80 by Nov 6. Re-seeded, a judge's demo reader
  starts at full strength through judging.
- `readiness_mix` (templates on 2026-10-04, feeds from 2026-10-11): newcomer 11 rows ready 7 /
  stretch 4; trader familiar 5 / ready 4 / stretch 2; policy student familiar 2 / ready 5 /
  stretch 2 / no line 2. Stop rule not hit.
- Live API revision `readlayer-api-00031-84x`, image digest `sha256:a91e6be8…0a95`;
  `git diff 9c5ad52 main -- apps/api` is empty, so 00031 already runs main's API code.
- Tavily: Sourabh, 2026-10-15: **324 credits left**; he supplies a new key when they run out.

## Steps, in order

**S1. Persona re-seed.** Pre-step. Dump the three current `persona_templates` docs to the
session scratchpad (restore path). `uv run python -m scripts.seed_personas` (dry run: re-check
the three lines above), then `--write`. Production write: **3 docs**, one transaction. Verify by
reading back: `graph_version 2026-10-10-folded-5206`, edge counts 109 / 86 / 115, `last_seen`
today. Cost $0.

**S2. Demo feed re-seed** (so the feed isn't dated 11 Oct during judging). Pre-step. Order:
Tavily credit check (done above: 324, ≥ 100 required) → outlet collection ran in the last 12 h
(read `rec_cache/outlets:*` update times) → `seed_demo_feed --dry-run` → real run, **both on the
same UTC day**. The dry run is not search-free: `build` calls `search.gather` and
`web.cached_entry` either way, so the dry run makes the ≤ 24 search calls and writes the
day-keyed `rec_cache` entries, and the real run reuses them. Check before the real run (STATUS
§9, M7.5 step 3): ≥ 2 readable articles per topic; a short persona is re-run with `--persona`.
Production writes: **3 docs** `persona_feeds/*` (public items only) + **≤ 18 `rec_cache`
entries**; ≈ 120 local fetches over both runs. Cost $0 LLM.

**S4. Readiness mix, gate** (after S1, S2): `scripts/readiness_mix.py`. It reads templates and
feeds straight from Firestore, so no restart is needed for it. Stop rule: one level on ≥ 80% of
the newcomer's rows → tell Sourabh, no retuning. This run is the gate only; the stretch lines for
the video come from S4b.

**S5. Media snapshots.** Pre-step. List the short videos and episodes in the three new
`persona_feeds` within the caps (≤ 10 min video, ≤ 12 min episode, length known).
`ingest_media.py <urls> --dry-run` (classification, window plan, cost estimate), then real,
**≤ 6 recordings** (one run, the script's cap), the newcomer's first. Stop rule for the
intermittent Vertex YouTube hang (STATUS §5): a timeout skips that URL, no re-run that day.
Recordings get **no growth** (`analyse_pending` without a reserver), so per recording print the
linked-demand count and the newcomer and trader annotation counts
(`/v1/content/{id}/annotations?persona=`), and choose the media shot from that (two personas must
get visibly different notes). Production write: ≤ 6 content docs (`user_ingested`, no reader).
Cost: the dry run's estimate, refused above $1.50 in total (media's own budget is $3/day).

**S6. Pre-ingest the feed's articles** with `apps/api/scripts/preingest_feed.py` (new, committed).
Candidates: the articles a fresh demo reader sees on the first page of For you (readiness_mix's
in-memory selection, articles only, de-duplicated, newcomer's and trader's rows first). It POSTs
each snapshot item's `url` exactly as stored (the content id is `url_hash` of the submitted
string) to the live `POST /v1/content` as anonymous demo users, ≤ 3 URLs each
(`ANON_INGEST_DAILY_CAP`), each user deleted in `finally` (as `warm_demo` does), paced.
Anonymous allowances are shared (`ANON_GLOBAL_INGEST_DAILY_CAP` 30 at `ops/ingest/days/{day}`;
`ANON_GROWTH_DAILY_CAP` 150 at `ops/growth/anon_days/{day}`), so the script:
- reads both counters first and prints them;
- caps the run at **min(20, 30 − used − 10)** URLs, leaving ≥ 10 ingests for people;
- stops when fewer than 25 anonymous growth slots are left;
- `--dry-run` prints the counters, the URL list and the count, and posts nothing.
It runs on **UTC day Oct 15** (the allowances reset at 05:30 IST Oct 16), before the video and
S9, which therefore get a fresh day. Afterwards: both counters recorded, any article left
`grow_pending` listed, dry-run output in STATUS. Production writes: ≤ 20 content docs + their
grown concepts. Cost ≈ $0.012 an article (ingest + growth) → ≤ $0.25.
The guards are small pure functions (URL cap, growth stop, de-duplication and persona order),
tested offline in `apps/api/tests/test_preingest_feed.py` with made-up counters, no network or
Firestore: used 0 → 20; used 15 → 5; used ≥ 20 → 0 and nothing posted; 24 growth slots left →
stops before the next URL; a URL in two personas' rows is posted once, newcomer and trader first.
Written test first; runs in CI with the PR.

**S3. Pick-up restart** (after S5 and S6; one restart covers both). Running API instances cache
templates per process (STATUS §5), and recordings written from the laptop by `ingest_media` never
reach a running instance's in-process catalog (library, Up next, explainer indexes). Templates
are also re-read whenever growth bumps `graph.version` (`+gN`, `graph/refresh.py`), but that is
not relied on. Mechanism: a same-image revision, as revision 00026 was: `make deploy-guard`, then
on **Sourabh's yes** `gcloud run services update readlayer-api --region asia-south1
--update-labels reseed=2026-10-16`. Required: a **new** serving revision (name differs from
`readlayer-api-00031-84x`, 00032 expected), created after S6 finished, serving 100%, image
digest equal to 00031's (`sha256:a91e6be8…`). If the labels update makes no new revision, the
fallback on the same yes is a no-op env update, `--update-env-vars RESEED_AT=2026-10-15` (the
00026 precedent). Record which mechanism produced the revision. No rebuild.

**S4b. Readiness mix, for the video** (after S3): `readiness_mix.py` again. Readiness comes from
`fr.named_concepts(graph, title + snippet)` against the served graph, and S6's growth adds
concepts, so the lines can move. Read every stretch line for the newcomer and trader. A wrong one
(e.g. "read up on Economic stocks and flows" on a stock-market video) is **kept out of the video
shot**; adding a known-wrong prerequisite is a code change, so it is offered to Sourabh, not done
under the freeze. Also compare the landing feed still's readiness lines with the live ones (STATUS
§5: "re-shoot only if a line becomes wrong") and report any that became wrong.

**S7. Choose the video article** with Sourabh: two personas side by side on one article, not the
BBC PFAS article (`cq8r6nzp4230o`). Default proposal: the Guardian Polymarket/HSBC article
(`99a2cb53…`, the "three frames" exhibit), unless an S6 article shows a clearer newcomer/trader
difference (checked with `/v1/content/{id}/annotations?persona=` for both). After S3, re-check
the chosen S5 recording's newcomer/trader difference the same way (S5 measured it on instances
that may still have held the old templates).

**S8. Warm explanations.** `warm_demo --shifts --dry-run` over the three `DEMO_ARTICLES` plus the
S7 article, then real. Expect ≤ 48 ±1-band Backgrounds per three articles (≈ $0.20; ≈ $0.27 with
the fourth). Pass 2 must be all cache hits; any capped card fails the run.

**S9. Live check and records** (UTC Oct 16 or later, a fresh day of allowances). A fresh anonymous
demo reader per persona on the live site: feed dated by S2's run; a pre-ingested article opens
without the "reading the page" wait; a seeded recording opens free; "Say it simpler" on the S7
article answers from cache. Each reader records one event, then before End demo read
`users/{uid}/demo_graphs/{persona}.template_version` and require the new version
(`{persona}@2026-10-10-folded-5206`). Then STATUS (new §33 acceptance, §7 spend, §9 Oct 16 row,
header), AUTOPILOT_LOG, milestone-reviewer → PR → CI → merge. For Sourabh's video and deck:
- End demo any existing demo session in the recording browser first (readers with a copy keep
  the old template, STATUS §5).
- The S7 article, the media shot from S5, the stretch rows to avoid from S4b.
- The deck numbers already fixed in STATUS §9: frozen-graph 64% / 13% vs 89% / 66%; precision
  87 / 97 / 90 labelled as judged by the build agent, and whether his audit is done.

## Production writes and spend, in total

| Step | Writes | Spend |
|---|---|---|
| S1 | 3 docs | $0 |
| S2 | 3 docs + ≤ 18 `rec_cache` entries; ≤ 24 searches; ≈ 120 local fetches | $0 LLM |
| S5 | ≤ 6 content docs | ≤ $1.50 |
| S6 | ≤ 20 content docs + grown concepts | ≤ $0.25 |
| S3 | 1 same-image revision (Sourabh's yes) | $0 |
| S8 | cache entries | ≈ $0.27 |
| **Total** | | **≤ $2.05** (STATUS §7 budgets ≤ $3) |

## Acceptance

S1 docs read back as stated; S2 feeds dated by the run with ≥ 2 readable articles per topic; S4
stop rule checked; S5 counts, per-recording note counts and spend recorded from `llm_calls`; S6
counters before and after, URLs posted, `grow_pending` list; `test_preingest_feed.py` passing
(locally and in CI); S3 a new revision (not 00031), created after S6, serving 100% with 00031's
digest, and the mechanism recorded; S4b mix and the landing comparison recorded; S8 pass 2 all hits; S9 live check
passed including `template_version`; STATUS and AUTOPILOT_LOG updated; milestone-reviewer SHIP;
CI green.

## If the day runs short

STATUS §9: stop and ask Sourabh what to cut (decision 27). Proposal to put to him: the fourth
warm article (S7/S8) first, then S6 (judges' clicks ingest live, slower), then S5. S1–S4 stay.
