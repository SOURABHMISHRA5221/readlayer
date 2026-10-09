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
