## Changelog (hand-written)

Rules (M5): the cases were written and committed before the first model run. Every later change
to `app/prompts/explain.md` or `app/prompts/verify.md` bumps its version header and gets an
entry here with the runs before and after. Cases are never edited to make them pass; a case
that turns out to be genuinely mislabelled is fixed only with the reason recorded here.

- **2026-10-10** Cases committed: 15 adversarial, 25 good (20 span, 5 paragraph mode, real
  corpus paragraphs from The Guardian, Wikipedia, Mint and The Economic Times), 10 injection.
  Prompts `explain-v1`, `verify-v1`.
