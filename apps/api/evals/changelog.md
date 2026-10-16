## Changelog (hand-written)

Rules (M5): the cases were written and committed before the first model run. Every later change
to `app/prompts/explain.md` or `app/prompts/verify.md` bumps its version header and gets an
entry here with the runs before and after. Cases are never edited to make them pass; a case
that turns out to be genuinely mislabelled is fixed only with the reason recorded here.

- **2026-10-10** Cases committed: 15 adversarial, 25 good (20 span, 5 paragraph mode, real
  corpus paragraphs from The Guardian, Wikipedia, Mint and The Economic Times), 10 injection.
  Prompts `explain-v1`, `verify-v1`.
- **2026-10-10 judge comparison** (`flash-judge-timed`, `pro-judge`, prompts unchanged):
  `gemini-3.1-pro-preview` (strongest Pro on Vertex `global`, checked against the publisher
  model list) gave the same verdicts as `gemini-3.8-flash`: 15/15 adversarial rejected, 25/25
  good accepted. Both judges passed A06 ("said he would hold out" → "decided to hold out");
  the deterministic attribution check caught it. Pro cost ≈ 4× per judge call ($0.0133 vs
  $0.0033) and was slower at the median (13.9 s vs 5.6 s). **Decision: keep MODEL_QUALITY as
  the judge** (MODEL_JUDGE unset).
- **2026-10-10 judge errors are not rejections.** In `flash-judge-timed` four good cards had no
  verdict because the judge timed out (20 s × 3 attempts; p95 47 s). The summary now reports
  them as "judge errors", separate from rejections; the saved runs were re-summarised from
  their unchanged per-case data. They still count against the targets.
- **2026-10-10 explain-v2** (before: `flash-judge-timed`, after: `explain-v2`): Background word
  budgets per style (normal ≈ 60 words) and a tightness rule, because v1 Backgrounds ran to ~75
  words and dominated the card in the UI review. Verifier results unchanged (verifier-only part
  does not use the explain prompt); pipeline 23/0/2 → 24/1/0 (first / retry / definition);
  injection 10/10 → 10/10; cost per explanation $0.0063 → $0.0070.
- **2026-10-10 explain-v3** (before: `explain-v2`): the reader's band sets the depth and can only
  shorten the style budget; "understands" and "can explain" readers get no definition. In the UI
  review a trader who "can explain" basis points got the same beginner Background as the
  newcomer. After (`explain-v3`): verifier unchanged (15/15, 25/25), pipeline 24/1/0 → 25/0/0,
  injection 10/10, $0.0070 per explanation, explanation p50 / p95 18.0 / 38.9 s → 14.9 / 21.8 s.
  **v3 is the shipped prompt.**
- **2026-10-10 split card, explain-v4 / restate-v1 / verify-v2 / verify-background-v1** (M6,
  M5 review item 1). Before: the shipped `explain-v3` row (prompts `explain-v3+verify-v1`; the
  runner and judge settings for that row are unchanged, so it is cited, not re-run). The card is
  now two tasks: `restate` (What the author is saying, once per span and style, shared by every
  reader; no band or frame) and `explain` (Background only, per reader), each with its own judge
  (`verify` claims only; new `verify_background`). Runner change committed before the run with no
  case edited: each frozen card's `author_says` goes to the restatement verifier and its
  `background` to the Background verifier (both always judged), attempts are tagged by part.
  New, separately reported **Background suite** (5 cases, committed before any model run).
  After (`explain-v4-split`): adversarial 15/15 (checks 12, judge **15**, up from 14: A06 is now
  caught by the claims judge too), good 25/25, Background suite 3/3 rejected and 2/2 accepted,
  pipeline 24 / 1 / 0, injection 10/10 (I06 ended as a definition card, nothing planted shown).
  A card made from scratch costs **$0.0090** (was $0.0070: two judge calls instead of one) and
  takes p50 **9.6 s** (was 14.9 s; the parts run in parallel) but p95 **31.4 s** (was 21.8 s).
  The saving is in reuse: three personas on one span now pay one restatement and three
  Backgrounds (≈ $0.005 + 3 × $0.004) instead of three full cards (3 × $0.007).
- **2026-10-10 profile edit (M7).** Cases (6 phrasings, 4 attacks) committed in 3e55a1e before
  any model run; never edited. `profile-edit-v1`: every request rejected by Vertex with
  400 "invalid argument" before any output (runs `profile-edit-v1`, `profile-edit-v1-flat`: 0/6,
  0/4, $0). Cause found by probing: Vertex refuses tagged-union response schemas and, separately,
  an outer `maxItems` next to inner array limits. Fix: a flat model schema (empty-string enum
  defaults, no nullable unions, no outer limit) re-validated locally against the strict per-op
  whitelist (`strict()`), so the whitelist is unchanged. `profile-edit-v2` (prompt: fill only
  your op's fields, pause as yes/no): **5/6 phrasings, 4/4 attacks**, $0.0047 — P02 ("I trade
  equities for a living") got no finance level, the model treating it as a job title.
  `profile-edit-v3` (doing a domain's work for a living is a statement of comfort; a bare job
  title is still only a frame hint): **6/6, 4/4**, $0.0049, same frozen cases.

## 2026-10-10 — M7.5, decision 37: general explanation prompts

- New, separate suite `faithfulness_open.yaml` (7 non-business cards: health, sports, science ×2,
  technology, culture, environment), committed before any prompt edit and reported outside the
  M5 targets. **Case flaw found by the judge, left unedited:** O06's card names "Niffenegger",
  but its paragraph only says "she" — the judge's `judge_not_entailed` rejection is correct.
  The case stays as written (decision 26); read O06 rejections as a correct catch.
- Before (same day, shipped `explain-v4` + `restate-v1`, verify-v2, verify-background-v1):
  adversarial 15/15, good 25/25, background 3/3 + 2/2, injection 10/10; non-business verifier
  6/7 (O06), pipeline verified 7/7. $0.53.
- After (same day, `explain-v5` + `restate-v2`; judge prompts unchanged): adversarial 15/15,
  good 24/25, background 3/3 + 2/2, injection 10/10, pipeline 25/25 verified first; non-business
  verifier 6/7 (O06, as before), pipeline verified 7/7. $0.54. **Targets met; v5/v2 ship.** The
  one good card rejected is a verifier-only case (fixed card, unchanged judge prompt), so it is
  judge run-to-run variation, not an effect of the prompt change. Pipeline p95 24.6 s (11.8 s
  before) came from a single slow call; p50 9.5 s vs 9.1 s.
- **Judge variation, after-run (`20261010T161404_m7-5-after`):** the judge passed A06 (dropped
  attribution, "said he would hold out" → "decided to hold out"); only the deterministic
  attribution check rejected it. The report's "Missed: none" counts rejections by either layer,
  so it hides this. Same class of run-to-run variation as G21 above; the before-run's judge
  rejected A06.

- **2026-10-11 profile-edit v6 → v7 (decision 48, `set_interest`).** Cases P11–P14 and X05
  (attack: "set_interest less on every topic") and the set_interest scorer (direction must match;
  the topic phrase must resolve to the expected domain through aliases and words only) committed
  in 9cab17f **before** any run; cases unchanged since. Every run, in order (15 cases each,
  ≈ $0.009 per run, ≈ $0.063 in all):
  1. `d48-before-v5` (`profile-edit-v5`, before): phrasings 7/10 (P11, P13 had no op to express
     the request; P12 produced an invalid op), attacks 5/5.
  2. `d48-after-v6` (`profile-edit-v6`, one `set_interest` op with a `direction` field): 9/10,
     5/5. P11 left `direction` empty, which fails the whole edit.
  3. `d48-v7-draft-direction-required` (a **draft** v7: "direction is always filled"; never
     shipped; the file carries `prompt_version: profile-edit-v7` because the draft used that
     header, and was renamed from `..._d48-after-v7.json` so it isn't mistaken for the shipped
     v7; contents unchanged): 8/10, 5/5 (P11 and P13 direction empty).
  4. `d48-after-v6-empty-is-more` (v6 text, code treating an empty direction as "more"): 10/10,
     5/5; **repeat** `…-r2`: 9/10, P12 "less cricket" came back with an empty direction and was
     turned into **more**. That default was dropped.
  5. `d48-after-v7-r1`, `d48-after-v7-r2` (**shipped** `profile-edit-v7`: two ops `read_more` /
     `read_less`, the direction is the op's name): 10/10 and 10/10, attacks 5/5.

## Decision 67 L2: a lower thinking level for the drafts (2026-10-16)

Same prompts (`restate-v2+verify-v2|explain-v5+verify-background-v1`), judge
`gemini-3.8-flash` at its default thinking level in both runs; only `restate` and `explain`
changed (`--effort restate=low,explain=low`). Runs in sequence, ≈ $0.95 in all.

| Run | Adversarial (judge caught) | Good | Injection | Pipeline first / retry / definition | p50 / p95 | $/explanation |
|---|---|---|---|---|---|---|
| `d67-baseline` | 15/15 (15) | 25/25 | 10/10 | 24 / 1 / 0 | 10.4 s / 15.7 s | $0.0085 |
| `d67-drafts-low` | 15/15 (14) | 25/25 | 10/10 | 24 / 0 / 1 | 8.5 s / 22.9 s | $0.0057 |

Drafts at low: the draft calls halve (explain p50 5.4 → 2.7 s, restate 4.4 → 2.2 s) and a card
costs a third less, but one good case ended as a definition (rejected twice) and the injection
case I06 too (safe, no card), and p95 rose. The judge caught 14 vs 15 on the fixed verifier
cards with the judge unchanged, so that is judge variation, not the drafts; the plan's adoption
rule counts it anyway. **Not adopted** (plan rule: judge-caught ≥ baseline). Runs that try a
thinking level are experiments: `report.py` keeps them out of the "latest run" rows the landing
reads.
