# Onboarding: knowledge from who you are, taste from what you pick (decision 68)

Sourabh, 2026-10-16 evening: "our onboarding is misleading our Map": on screen 2 the "Know X?"
chip on every card writes to the knowledge map from a quick tap; "What they do and where they are
from builds knowledge", and screen 2's picks should inform the feed only; add "audio, video and
reading as one preference question in onboarding" and use it for the card chips and the
end-of-article Up next; screen 2 should offer video and audio tiles too; and the chips and Up next
"where not seen for new sign in", only in demo accounts. Then: "'Know this?', Helpfull and all are
indicators for knowledge building .... On screen two decision do what u feel is best". Freeze lifted
for this work (decision 68, STATUS §10). The re-recorded video (Sourabh's new script) comes after
this is live.

**Two PRs.** PR A = **B** (chips on fresh links; it affects the "Read any link" step for every
reader), branch `d68-chips-ready`, shipped first. PR B = **R0 + K + F**, branch `d68-onboarding`.
**Checkpoint Oct 17 12:00 IST:** PR B not harness-green → ask Sourabh to cut, proposing F4's
minimum-per-format rule first, then F3, then K4, then K2.

## What is wrong today (read from the code and production logs, 2026-10-16)

- Screen 2 (`DiscoverScreen`): each card has "I'd read this / Not for me" (interest ± 0.15 in the
  item's domain, a rec signal) **and** "Know <term>? Yes / Not really" → `POST /v1/onboarding/know`
  → `apply_answer`: strong `calibration_answer` evidence on the concept and an Elo step
  (`ELO_K_ONBOARDING`) on its domain θ. The readback says "you know X". A quick tap becomes a
  claim on the map.
- Screen 1 (field, country, topics) writes **no** knowledge: field only suggests an analogy frame
  (`FIELD_FRAME`); `comfort` and `liked_content_ids` are accepted by `POST /v1/onboarding` but the
  2-screen UI sends neither, so a new account starts at θ 0 everywhere.
- No format question. Signed-in readers rank with the fixed `default` prior (articles 0.6, video
  0.5, podcast 0.45) in Up next, chips and the feed (`feed_router.get_feed` → `FeedReader.prior`);
  the feed takes 3 articles, 2 videos, 1 podcast per topic (`feed_rank.QUOTAS`); screen 2 orders
  articles first (`onboarding_mix`), so 9 cards are almost all articles.
- **Bug, chips for fresh links:** production logs (2026-10-16 ≈ 15:57 and 16:00 UTC, signed-in)
  show `GET …/recommendations?basis=article` → **409** `content_pending`: the web asks once at page
  load, before a just-opened link is analysed, and `loadNextUp` drops the error. Up next (asked
  after the notes resolve) answered 200 and polled while its lookups ran; whether it rendered for
  a fresh account is unverified (R0).

## PR A: B. Chips once the notes are ready

`useAnnotator` starts `loadNextUp` only when the page's notes have loaded (a `ready` flag from
`ReaderPage`, the same gate that holds back `UpNext` and `Recap`), so a just-opened link asks after
its analysis (which can take up to the 120 s analyse timeout). One 409 retry after 3 s remains as
a fallback. Vitest: no request while not ready; a request and items once ready; a 409 retried
once. STATUS §36, DESIGN §16.1 one line. Ship: milestone-reviewer → PR → CI → merge →
`make deploy-web` (Sourabh's yes; web only).

## PR B

**R0. Reproduce first (local harness).** `make dev-emulator` + a new `tools/shots/fresh_account.py`
(Auth-emulator "Google" account, test values only): sign in fresh → consent → onboarding → open a
library article and a pasted link → record per page the `/recommendations` calls (status, `items`
count, `pending`), whether chips and Up next render, screenshots. Further causes found are fixed in
PR B with a test and recorded in STATUS §36; none → recorded as such. **Cost bound per run:** ≤ 2
pasted-link analyses (≈ $0.005 each) and growth on them (≈ $0.01), the onboarding searches
`tools/shots/onboarding.py` states (≤ 18 topic + ≤ 2 concept searches: ≤ 20 Tavily credits, ≤ 12
YouTube calls) and Up next / chips lookups for 2 pages (≤ 12 Tavily, ≤ 12 YouTube); ≤ 3 runs. The
Tavily balance on the new key is printed before and after (`warm_next_up`'s stop rule is unaffected:
its run is done).

**K. Knowledge from screen 1 only.**
- **K1. Field → starting θ.** `onboarding.FIELD_THETA` (pure): software → technology; finance →
  finance, economics; commerce → business; law → law; science → science; medicine → health;
  teaching → education; design and other → none (a design chip doesn't claim all of culture);
  each at `LEVEL_THETA["comfortable"]` (0.5). Applied by `POST /v1/onboarding` on a **first-time**
  submit only: `comfort`, when sent, overrides it per domain; when Edit → Continue changes the
  field before finishing, the previous field's `FIELD_THETA` domains are reset to 0 (unless
  `comfort` sets them) before the new ones apply. **Not applied on a Redo** (`theta = {}` there
  today, decision 48). Tests: mapping, comfort override, field switch resets, redo untouched.
- **K2. Country → a few home terms, gently.** `onboarding.home_terms(graph, country, state, now)`
  (pure): for IN / GB / US, graph concepts with `jurisdiction` = that country and `doc_freq ≥ 3`,
  most frequent first, at most `HOME_TERMS = 25`, **skipping** any concept whose edge already holds
  a `home_country` evidence entry (idempotent across Edit → Continue and Redo) and any whose
  p after the nudge would be ≥ 0.8 (p computed from the reader's existing edge when there is one,
  else the prior). Each gets one evidence step of the new kind `home_country`
  (weight 0.2), written **without a band move** (no `band_prev` / `band_changed_at`, so
  `moved_up_this_week` stays empty after onboarding). "other" → none. Profile evidence text:
  "Common where you read from". Counts per country on the production graph recorded in §36
  (the seeded graph gives ≈ 13 IN, 13 GB, 19 US). Tests: jurisdiction and doc_freq filter, the
  0.8 cap (from the prior, and from an existing edge), idempotence over two POSTs and one redo (exactly one entry), no band move,
  `moved_up_this_week` empty.
- **K3. Screen 2 writes no knowledge.** The "Know X?" chip is removed from the cards;
  `_term_out` returns None for every item (also for terms already offered to a reader mid-
  onboarding); `POST /v1/onboarding/know` becomes a **200 no-op** `{"saved": false}` that writes
  nothing (a non-2xx would show an old client "That answer didn't save"); kept until after judging
  (STATUS §5). The readback drops "you know …" / "… is new to you". In-article signals stay the
  knowledge evidence (DESIGN §6: Know this? prompts, Knew this, Helpful, opening a note). Tests:
  discover returns `know: null`; a know call changes no edge and no θ; a pick writes no edge.

- **K4. A separate "Quick check" at the bottom of screen 2** (Sourabh, 2026-10-16 late: "keep
  similar to second screen a know this cards to build a basic knowledge" → "second screen bottom
  only"). Under the taste cards, clearly apart from them: a heading "Quick check: do you know
  these?" and **one term card at a time** from the existing adaptive calibration
  (`GET /v1/calibration/next`, `POST /v1/calibration/answer`; terms from the chosen topics,
  closest to the reader's θ, which K1 has set): the term, its topic, and "Know it" / "Heard of it" /
  "New to me" (`explain` / `heard` / `none`: the reader's own word, strong `calibration_answer`
  evidence and an onboarding-strength Elo step, DESIGN §4/§6, unchanged). `CALIBRATION_ITEMS`
  8 → 6 (`tests/test_onboarding.py` loops follow the constant, so the change shows there).
  "Skip quick check" only hides the block (it never calls `/calibration/skip`, which finishes
  onboarding). **Only `POST /v1/onboarding/finish` ends onboarding:** `calibration_answer` no
  longer sets `onboarding_done` on the last answer (today it does, which would close screen 2 under
  the reader: discover and pick → 409); its `done` is about the quick check alone. **No term twice:**
  a first-time re-submit of screen 1 (Edit → Continue) keeps `calibration.asked` and the answer
  count (a redo already does), so the check resumes or shows done. **Hidden on a Redo** (onboarding
  stays done there and the calibration routes refuse; the web knows from the redo step). Progress
  "2 of 6"; done → "Thanks — that's your starting map"; after an answer, focus moves to the next
  card or the done line. Note: K1's field switch resets the old field's domains to 0, which also
  drops any Elo moves quick-check answers made there (minor; the edges stay).
  Tests: API (answer 6, then pick and discover still 200, finish then clears the lists; POST,
  answer 2, POST again → `next` never returns an asked term and `answers` stays 2); web (one card
  at a time, answer posts and shows the next, skip calls nothing, done state, hidden on a redo,
  focus after an answer).

- **K4b. The Quick check shows all six at once** (Sourabh, 2026-10-17 after K4 shipped: "on
  second onboarding page 6 questions should be a single answer all in one go thing not answer one
  then see next"). PR C, branch `d68-quick-set`.
  - API: `onboarding.quick_set(graph, interests, θ, asked)` (pure): the terms already answered
    first (a reader mid-way through the old one-at-a-time flow keeps them, shown as answered),
    then `next_item` repeated with each pick counted as asked, up to `CALIBRATION_ITEMS` (6) in
    all — chosen at once from the current θ, no longer adaptive between answers.
    `GET /v1/calibration/set` → `{done, total: 6, items: [{concept_id, label, domain, answered}]}`;
    the set is created **in one transaction** that returns an already-stored set unchanged
    (`ReaderRepo.calibration_set`), so overlapping first asks (StrictMode, a reload, a second tab)
    see one set; done when every item is answered; `{done: true, items: []}` after finish.
    `POST /v1/calibration/answer` accepts any unanswered item of the stored set (each once; evidence
    and Elo unchanged; `calibration_answer` keeps the stored set), or — with no set stored, an old
    client — the current `next` item as today. `GET /v1/calibration/next` returns the first
    unanswered set item when a set exists (the live old web keeps working through the deploy).
    **Edit → Continue** (a first-time re-submit) keeps `asked` but drops the stored set, so the
    unanswered part is rebuilt from the new topics and θ (never an asked term). Never finishes
    onboarding. Tests: 6 distinct terms, stable on a second call even after θ moves, any order,
    a repeat or an outside term 409, done after 6, closed after finish; 2 answered before the set
    → 6 rows with 4 open, all accepted; Edit with new topics → answered kept, the rest from the new
    topics, `answers` unchanged; the old sequential `next` gets the first unanswered set item.
  - Web: the Quick check lists all items, each row the term, its topic and "Know it" / "Heard of
    it" / "New to me" (`role="group"`, the chosen one `aria-pressed`, answered rows stay focusable
    with `aria-disabled`); answering any row in any order; "Skip quick check" hides the block;
    all answered → "Thanks, that's your starting map." Tests: all rows render, answers in any
    order post the right ids, a row can't be answered twice, done after all, skip calls nothing,
    hidden on a redo. Harness: `tools/shots/onboarding.py` answers two rows out of order.
  - Acceptance evidence: the harness (`tools/shots/onboarding.py` answering two rows out of order)
    with the UI checks on the multi-row block (axe 0, target sizes, no horizontal scroll at 390
    and 1440, light and dark); before the web deploy, the old sequential web against the new API
    on the harness (`next` → the first unanswered set item). The Quick check is hidden on a Redo,
    so Sourabh's own account can't exercise it; a production check would need a fresh Google
    account on his yes, deleted afterwards (writes: one user doc, ≤ 6 edges, ≤ 14 domain docs).
  - Ship: API first, then web (the old web keeps working on the new API).

**F. Read, watch, listen.**
- **F1. Screen 1 question** "How do you like to take things in?" — Read / Watch / Listen, any of
  them; none preselected on a first run, the stored ones preselected on a Redo; Continue needs at
  least one. API: `OnboardingIn.formats: list[Format] = []` (≤ 3, deduplicated), **optional**
  (the API deploys first and the old web sends none); empty → the stored value is kept (or, for a
  new user, none: the default prior applies). Stored on the user (`UserProfile.formats`),
  returned by `GET /v1/me/profile`, covered by export and delete (it is on the user doc).
- **F2. Ranking.** `rank.format_prior(formats)` (pure): chosen formats mean 0.75, the others 0.4;
  used instead of `default` for a signed-in reader with formats in Up next and the chips
  (`recs/router.py`) **and** in the feed (`feed_router.get_feed` → `FeedReader.prior`). Card chips
  (`one_per_format`) are ordered chosen formats first, then the rest (read, watch, listen within
  each group). Format affinity from clicks and shown items keeps adjusting on top (DESIGN §16.4).
- **F3. Feed quotas.** `feed_rank.quotas_for(formats)` (pure): a chosen format's quota is raised
  to 3 (podcast 2), an unchosen one lowered to 1 (articles 2); all three or none → today's
  quotas. Used by `select` for a signed-in reader's live feed; demo snapshots unchanged.
- **F4. Screen 2 tiles.** `onboarding_mix(groups, now, limit, formats, served)`: items already
  served to this reader keep their served order and slots (a later poll's videos never push out a
  card the reader may have answered); remaining slots fill chosen formats first (then fresher),
  with at least 2 of each chosen non-article format and 1 of each other format when the searches
  returned any. Each card shows its format word and length ("Watch · 6 min", "Listen · 24 min");
  the like button reads "I'd read this" / "I'd watch this" / "I'd listen to this". A pick already
  records a rec signal with the item's format. Tests: served items stable across polls, minimums,
  chosen first.

**Harness and UI checks.** `tools/shots/onboarding.py` updated (no `.discover-card__know` clicks; a
format step; the Quick check: one card answered, then skipped). §19-style checks for the format question, the card format words and the Quick check (its three answer buttons' target sizes): axe 0, target
sizes, no horizontal scroll at 390 and 1440 px, light and dark.

## Tests first (PR B)

API: `test_onboarding.py` (FIELD_THETA, field switch, home_terms filters and cap, idempotence, no
band move, `_term_out` None), `test_onboarding_flow.py` (POST /v1/onboarding θ and home-term
edges, formats optional/stored/kept on redo, know no-op, discover `know: null`, a pick writes no
edge, `moved_up_this_week` empty), `test_recs_rank.py` (format_prior, chip order), `test_feed_rank.py`
(quotas_for, onboarding_mix), `test_feed_api.py` / `test_recs_api.py` (a signed-in reader with
formats: the chosen format gets the 3-slot quota in the feed, and the first chip is that format).
Web: AboutScreen format question (required, preselected on redo, sent), DiscoverScreen without
"Know X?" and with format words, readback without knowledge clauses, profile evidence text; the
wording guard still passes.

## Docs

DESIGN §4 (onboarding screens; the calibration bullet: 6 items, now inside screen 2's Quick check, never finishing onboarding), §5/§6 (θ from field, `home_country` evidence, no knowledge from
screen 2), §11.4 and `PrivacyPage.tsx` (country now also picks a few home terms; field sets a
starting level; formats held; the "Know this? answers … stay as evidence" line updated), §16.1 (B),
§16.4 (format prior), §17.2 (feed quotas and prior); README line 65 (no "Know this?" on screen 2);
STATUS §10 decision 68, §9 (PR A, PR B, the checkpoint), §5 (the no-op know route), §36; AUTOPILOT_LOG.

## Live checks (STATUS §36)

- PR A: one pasted link in production (a demo account) gets chips after its notes arrive; that page
  is deleted afterwards (as the M7.5 live check did; one content doc, its growth ≈ $0.01).
- PR B, harness: a fresh account picking Software + India + Watch → technology θ 0.5; ≤ 25 Indian
  terms with one `home_country` entry each, bands as computed (recorded), nothing from screen 2,
  "moved up this week" empty; screen 2 shows ≥ 2 videos; the first chip is Watch; the feed gives
  videos the 3-slot quota; a pasted link gets chips.
- PR B, production, on Sourabh's yes: his own account through **Redo setup** (adds formats; on a
  redo FIELD_THETA is not applied and home terms skip any already given) — expected writes: the
  user doc's `formats`, ≤ 25 `home_country` edges, no θ change. A throwaway account is not created
  by the agent.

## Ship

PR A first (above). PR B: milestone-reviewer → PR → CI → merge → `make deploy-api` (Sourabh's yes)
→ **then** `make deploy-web` (yes): the old API's `extra="forbid"` would reject `formats`, so the
web never deploys before the API. Spend: R0's bound above (≤ 3 runs: ≤ $0.05 models, ≤ 96 Tavily
credits, ≤ 72 YouTube calls); live checks ≈ $0.01. Undo: revert; existing accounts keep what they
have (no migration).
