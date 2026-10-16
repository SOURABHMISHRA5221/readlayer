# Consumer wording, next-up chips, analogy toggle, faster cards (decision 67)

Branch `d67-consumer-card`. Sourabh, 2026-10-16, after the demo video: change "reader" to
"consumer", Margo → Gloss; a teammate's idea: chips in the note card suggesting what to read /
watch / listen next, **based on the article's content, not the word**; the analogy frame offered
both from the chips the person picked and "for you" (from their map and reading), as a toggle in
the same card; lower LLM latency without losing much quality. Sourabh: "yes lets fix them all",
in the order R → L → N → A. This lifts the Oct 16 code freeze for this work only (decision 67,
STATUS §10).

**Two PRs.** PR 1 = R + L (merged and deployed first). PR 2 = N + A (branch
`d67-chips-frames` from main after PR 1). **Checkpoint 23:00 IST Oct 16**: if PR 2 isn't
harness-green by then, ask Sourabh whether to cut A first, then N. Oct 17 keeps its rows
(`/v2` removal, gitleaks, submission); STATUS §9 gains the Oct 16 and Oct 17 rows for this work.

Web and API only: the extension shows neither word and gets none of the new card options (needs
a 0.8.3 release; STATUS §5). `/v2` untouched ("no action on v2").

## R. Wording: "consumer", and Gloss instead of Margo (PR 1)

- **R1. What changes.** User-visible text in `apps/web/src` (excluding `landing/v2/`) and
  `packages/annotator/src`: JSX text, string literals shown on screen, `alt`, `aria-label`,
  `title`, placeholders, document titles.
  - "reader(s)" meaning the person → "consumer(s)" ("Try it as a demo consumer", "Sample
    consumers, nothing tied to you", "this sample consumer", "Every consumer gets the same
    article…"). Grammar fixed per sentence, not by blind replace.
  - "reader" meaning the reading view ("The Gloss reader on a laptop") → "Gloss".
  - "Margo" → "Gloss" ("Tell Gloss about you", "Gloss learns what you know"); `alt` texts naming
    the character say "the Gloss mascot". The drawing, `Margo*` component names, CSS classes and
    file names stay (code, not copy).
- **R2. API text shown on screen.** Strings the API returns for display (`why` lines, readiness
  lines, profile summary, error `detail`s the web shows) are searched for "reader"/"Margo" and
  changed the same way; field names, routes, task names, log text and prompts are unchanged.
- **R3. Not changed.** Code identifiers, routes, API fields, Firestore names, prompts (no version
  bump), README and the deck (Sourabh's call, STATUS §5). DESIGN prose keeps "reader" as the
  internal term; DESIGN §19 notes the UI word is "consumer" and the mascot isn't named in the UI.
- **R4. Guard test (tests first).** `apps/web/test/wording.test.ts` walks every `.ts`/`.tsx` under
  `apps/web/src` (except `landing/v2/`) and `packages/annotator/src` with the TypeScript compiler
  API and flags every string literal, template-literal text and `JsxText` matching
  `/\breaders?\b/i` or `/\bMargo\b/`, skipping only: `className` attribute values, import /
  export specifiers, property-name keys and comments. Code strings that must keep the word
  (e.g. a route key `"reader"`, an event field `reader:`) are renamed nowhere: they are keys or
  get a one-line `// wording-ok: <reason>` comment on the line, which the test honours. Existing
  tests asserting old copy are updated (`landingV2.test.tsx` untouched). API: one pytest asserts
  the R2 strings.

## L. Faster cards without losing quality (PR 1)

Today (STATUS §7, ops report Oct 8–14): cached card p95 127 ms (70 % of opens), a generated card
p50 9.6 s, p95 30–31 s. Each part (restatement, Background) is drafted then judged in sequence on
`MODEL_QUALITY`, both parts in parallel, one retry on rejection. Gemini 3 thinking is at the
model default for these four tasks.

- **L1. Per-task reasoning effort from settings.** `Settings.llm_reasoning_effort` (env
  `LLM_REASONING_EFFORT`, JSON task → "low"|"medium"|"high", default `{}`) overrides
  `Route.reasoning_effort` for the structured-call path (`llm.py`'s call kwargs); validated
  against known tasks and levels at startup. It does **not** apply to `transcribe()`, which keeps
  its own route effort (`llm.py:636`). `evals.run` gains `--effort task=level,...`, which sets it
  for the run and saves it with the result.
- **L2. Measure, then adopt (drafts only).** The judges keep the model default: run-to-run judge
  variation is recorded (`evals/changelog.md`: A06, G21), and a weaker judge could hide behind
  the deterministic checks. Two runs of `evals.run --suite safety`, saved with labels and timings:
  baseline (`{}`) and drafts low (`restate`, `explain` = low). Adopted only if drafts-low has:
  every adversarial card rejected **and** `adversarial_caught_by_judge` ≥ baseline; good accepted
  ≥ baseline; injection 10/10 safe; `pipeline_verified_first` ≥ baseline − 1 (more retries make
  cards slower); and a lower pipeline p50. Otherwise nothing changes. The adopted value goes in
  `.env.example`, the Cloud Run env set by `make deploy-api`, STATUS §7 and DESIGN §7.
- **L3. Prefetch notes as they come into view (web, signed-in only).** Today the top 3 notes per
  page prefetch on load (`PREFETCH_TOP`). For **signed-in** consumers only, a note whose mark
  comes within one screen of the viewport (`IntersectionObserver`, `rootMargin` = viewport height)
  is also prefetched, at most `PREFETCH_MAX = 10` per page in total, at most 2 in flight, never
  "simpler/deeper". Anonymous (demo) consumers keep `PREFETCH_TOP = 3` (their 40-a-day and the
  shared 400-a-day caps are for clicks). A prefetch result with `capped: true` (the daily cap
  answers 200 with a definition; 429 is only the per-minute limit) is **not** kept in the page
  cache, so a later click asks again. Prefetch uses the page's current frame choice (pick unless
  the person switched to "For you" on this page, part A). Cost bound: ≤ 10 cards per signed-in
  page view, ≈ $0.09 worst case, inside `explain_daily_cap` 100.
- **Deferred (STATUS §5):** showing each card half as soon as it passes (two requests per card,
  reworks the daily-cap reservation); a faster or lower-effort judge (faithfulness first).

## N. Next-up chips in the card, from the article (PR 2)

- **N1. API.** `GET /v1/content/{id}/recommendations` gains `basis: "consumer" | "article"`
  (default "consumer": today's behaviour, the end-of-article Up next). With `article`:
  - Triggers are the article's own key ideas, `feed_rank.key_ideas(doc, graph)` (its 4 most
    salient linked concepts, the same for everyone), not the person's new spans. Library
    candidates and web lookups (`WEB_TRIGGERS` = 3 ideas × configured formats, the same
    per-(concept, format) cache and `build_query` (label + domain + format suffix only), the same
    anonymous search allowance) use them; relevance by salience order instead of span score.
  - `items` hold at most one per format, in the order article, video, podcast
    (`recs.rank.one_per_format`, pure); `why` says "On ‘X’, a key idea here" (new `_why` case).
  - Served items are remembered as today (consent rule unchanged). Docs with no linked ideas
    return `items: []`.
- **N2. Annotator (no framework).** New options `nextUp?: () => NextUpChip[]` (read when a card
  opens), `onNextUp?: (chip) => void` and `onNextUpShown?: (ids: string[]) => void`.
  `NextUpChip = { id, format, title, source, href, minutes }`. "Up next" sits **at the end of the
  scrolling card body** (not the pinned footer, which would squeeze the phone sheet): one row of
  up to 3 chips that scrolls horizontally when narrow; each chip a format icon + "Read" / "Watch"
  / "Listen", the title (one line, ellipsis), the source; each an `<a href>` (keyboard,
  middle-click) whose click calls `onNextUp` and prevents default. `onNextUpShown` fires when the
  chip row is first visible in a card. Span and paragraph cards; not in `actions: "demo"` or
  `inline` cards; no chips → no section. Styles in `styles.ts`. Tests: rendering, empty, click,
  keyboard, shown callback.
- **N3. Web.** `ReaderPage` and `MediaReader` fetch `basis=article` once per page (aborted on
  unmount; while `pending`, polled like `UpNext` with the same limit), map to chips and pass them
  to the annotator. Clicks reuse `UpNext`'s open logic, extracted to `lib/openRec.ts` (library →
  the reader route; `open_here` web items → `POST /v1/recs/open`; else a new tab) and send the
  same `click` rec event; `onNextUpShown` sends `rec_shown` **once per chip per page** (DESIGN
  §16.4–16.6 format affinity needs shown-without-click). Vitest for the mapping, the shared opener
  and the once-per-page `rec_shown`.
- **N4. Search credits.** `basis=article` adds up to 3 ideas × 3 formats lookups per uncached
  article (Tavily ≈ 318 credits left, STATUS §5). Before judging, `scripts/warm_next_up.py`
  (`--dry-run` prints the demo articles' key ideas, the `rec_cache` misses and the Tavily /
  YouTube calls it would make, the Tavily count on its own line; `--write` only on Sourabh's
  yes) fills the cache for `warm_demo.DEMO_ARTICLES` plus the 16 pre-ingested first-page
  articles. Tavily serves article and podcast: worst case 22 × 3 × 2 = 132 of ≈ 318 credits.
  **Stop rule:** more than 150 Tavily calls in the dry run → warm only the demo articles.

## A. Analogy frame: "Your pick" and "For you" in the card (PR 2)

- **A1. Frames.** Today the frame is one of `THINKS_IN` (12 fields picked in onboarding or the
  profile; personas fixed: newcomer software, trader cricket, policy student law). A "for you"
  frame comes from the knowledge map: `Frame = ThinksIn | MapFrame`, taxonomy domains mapped:
  technology → software, health → medicine, education → teaching, law → law, science → science;
  economics, finance, business, policy, politics, environment, sports, culture, society are
  frames by their own name (`MapFrame`).
- **A1a. Widen the closed type.** `ThinksIn` is a `Literal` that types the explain task's
  structured output and the served card. All of these become `Frame`:
  `BackgroundDraft.analogy_domain` (**the explain task's output schema changes**: the model may
  now answer a `MapFrame`), `Explanation` and `Card` (`explain/models.py`),
  `ExplainInputs.thinks_in` (`explain/inputs.py`), `ExplainResponse.analogy_domain` and
  `.thinks_in` (`explain/router.py`). `service._frame` still drops a label different from the
  frame asked for. **No prompt-version change**: the prompt text is unchanged and widening an
  enum only adds allowed values, so existing cached Backgrounds (whose keys hash the prompt
  version, `explain/inputs.py`) stay valid, including the warmed demo and `--shifts` cards. The
  schema change is recorded in DESIGN §7 and STATUS §10 instead. The onboarding/profile pick list
  stays `THINKS_IN`. Pytest: a `MapFrame` survives `_frame` and is served with its label; another
  pins `service.prompt_version()` (and the restate/background versions) to their current values,
  so a later edit can't silently invalidate the cache before judging.
- **A2. `reader/frames.for_you(state, graph, exclude_domain, now) -> Frame | None`** (pure, unit
  tested). Iterates the person's **edges only** (the reading and answers they actually gave, not
  the graph or the prior): a concept counts when `model.current_p_know(edge, prior, now) ≥
  KNOWN_P` (0.5, forgetting applied). Domains with ≥ 3 such concepts qualify; ranked by count,
  then mean p, then taxonomy order; the note's own domain is excluded (an analogy from the same
  field explains nothing); mapped by A1. None when nothing qualifies. (This is not the map's
  "solid", which uses `band_of(p) != unaware` with the prior.)
- **A3. API.** `ExplainRequest.frame: "pick" | "for_you" = "pick"`. The response gains `frames:
  { pick: str | None, for_you: str | None, used: "pick" | "for_you" }`, computed for every card
  from the state already read. `for_you` with no for-you frame serves the pick and says `used:
  "pick"`. Same verified path, cache (the Background key holds the frame) and rate limits as
  `shift`; `frame` and `shift` combine. Paragraph mode excludes the domain of the paragraph's
  first concept.
- **A4. Card.** When `for_you` exists and differs from `pick` (after A1 mapping), the
  Background's label line becomes a two-option toggle (`role="radiogroup"`, arrow keys), the used
  one selected: "Your pick · Software" / "For you · Finance"; with no pick, "No analogy" / "For
  you · Finance" (so a signed-in person who never picked still gets it). Choosing the other calls
  the new option `loadFramed(annotation, frame)` (only on click) and shows the skeleton then the
  result, like simpler/deeper. The choice is remembered for the page (the host passes it to later
  `loadExplanation` calls and to L3's prefetch). Otherwise the label stays "Analogy · X".
  Picking chips stays in onboarding and the profile.
- **A5. Eval of the new frames.** `evals.run` gains `--frame <name>` (sets every case's frame;
  cases unedited). After A is built: the Background pipeline on the frozen 25 good cases with
  `--frame finance`, plus one full safety run with the adopted L2 effort; verified-first / retry /
  definition reported against the L2 baseline. A drop of more than 2 in verified-first → stop and
  tell Sourabh before PR 2.
- **A6. Warm the toggle for the demo.** `warm_demo --for-you` (dry run first: entries and $
  printed) generates the for-you Backgrounds for the trader and the policy student on the
  Guardian video article's notes, so a judge's first flip is cached (≈ 27 notes × 2 personas,
  ≈ $0.004 each ≈ $0.22).
- **Personas, expected:** newcomer pick software, for-you likely technology → software (same: no
  toggle); trader pick cricket, for-you finance (economics on finance notes); policy student pick
  law, for-you policy or politics. Measured on the demo articles and recorded.

## Docs

STATUS §10 decision 67 (freeze lifted for this work); §9 rows; §5 deferred items (extension
0.8.3, README/deck wording, progressive card, judge effort). DESIGN §7 (frame toggle, `MapFrame`
mapping, `analogy_domain` no longer limited to THINKS_IN, effort per task); §11.3 (the for-you
frame is a word from a fixed list derived per person; no history reaches a model); §16.1
(`basis=article` triggers, one per format); §16.3 (tests pin article-basis queries to label +
domain + suffix); §19 (UI wording).

## Tests first, then build (per part)

API pytest: L1 (override validation, kwargs, transcribe untouched), N1 (article triggers, one per
format, empty doc, consent unchanged, query shape), A1a/A2/A3 (widened types, `_frame`, qualify,
exclude own domain, edges only, ties, mapping, None, request validation, `frames` in the response,
for_you fallback, cache key differs by frame); ruff. Web/annotator: R4, L3 (signed-in only,
capped not cached, cap of 10, 2 in flight), N2, N3, A4; `pnpm -r typecheck`, `pnpm -r test`;
375 px screenshot of the phone sheet with chips and the toggle.

## Measurement and live checks (STATUS §35)

- L2's runs: p50/p95 and the safety numbers per config; the adopted config. A5's numbers.
- After each deploy: one cold card per persona on a non-demo article (time to card); for a
  signed-in session, the prefetch count in the network log for one page; chips on the Guardian
  article per persona (≤ 3, about the article's ideas, `rec_shown` sent once); the trader's
  toggle (cricket ↔ finance) cached and verified; no "reader"/"Margo" on the landing, onboarding
  and reader pages.

## Ship

PR 1: milestone-reviewer → PR → CI → merge → `make deploy-api` (Sourabh's yes; carries the
adopted `LLM_REASONING_EFFORT`) → `make deploy-web` (yes) → live checks.
PR 2: same, then `warm_next_up --write` and `warm_demo --for-you` on Sourabh's yes.

**Spend:** L2 two safety runs ≈ $1.10; A5 ≈ $0.80; A6 ≈ $0.22; live checks ≈ $0.10; total ≤ $2.50
of models (daily guard $8 applies). Tavily / YouTube: N4's dry-run counts (≤ 22 articles × 3
ideas × 3 formats worst case, most already cached), within the ≈ 318 credits. Undo: revert the
web deploy; clear `LLM_REASONING_EFFORT` on the service.
