# README refresh (Oct 16 item, pulled to 2026-10-14)

Sourabh, 2026-10-14: asked how much effort the README needs, then "Do it today". The repo is now
public (decision 62), so the README is what judges and visitors read first. Docs only: no code, no
deploy, no production writes. Branch `readme-refresh` from `main` (540bc80).

## What is wrong today (README at 540bc80)
- "Where we are" and the Roadmap stop at M4: M5 (verified explanations, safety evals), the rest of
  M6, M7, M7.5, the design pass, landing and onboarding, media, M9, readiness and decision 62 are
  live (STATUS §1) but shown as in progress or missing. The three "† In progress" footnotes
  (Features, How it works, How Gen AI, Responsible AI) are false.
- "Beyond the hackathon. Videos and podcasts appear today as recommendations only" is false since
  decision 54 (STATUS §9 Oct 16 names this line).
- Features miss: For you feed with readiness lines, reading goals and Read any link, onboarding and
  calibration, the reading profile with its knowledge map and edit-by-prompt, paragraph notes /
  pre-read / "Know this?", videos and podcasts with transcripts, the Chrome extension (and Open in
  Gloss), "This is wrong" reports.
- Evaluation misses the safety evals (`apps/api/evals/report.md`: adversarial 15/15, good 24/25,
  injection 10/10 on the latest prompts).
- How Gen AI misses `transcribe` (MODEL_QUALITY, Gemini 3.8 Flash; `llm.py` route) and that
  `verify` / `verify_background` use the judge model (MODEL_JUDGE, empty → MODEL_QUALITY).
- Architecture omits `media/` and the extension as a client; the Repository structure omits
  `media/`, `content/`, `privacy/`, `apps/api/evals/`, `tools/shots/`.
- Getting started says the Makefile names our `ACCOUNT` at the top; since decision 62 (R12) it
  comes from a gitignored `.gcp.local.mk`.
- Screenshots and the hero image predate the design pass (the hero caption says so).
- Team is a placeholder table.

## Changes
1. **Hero and screenshots** use the landing's current stills, referenced in place from
   `apps/web/public/landing/` (1x WebP; GitHub renders WebP), with the landing's alt texts verbatim
   (already checked against the stills): `shot-reader` (hero), `shot-feed`, `shot-media`,
   `shot-extension`, `shot-phone`. `personas.png` and `demo.gif` stay (they carry the
   three-readers claim; caption notes they show the pre-rename UI). Old `hero.png`, `library.png`,
   `dark.png`, `mobile.png` stop being referenced (files kept; deleting them is not needed).
2. **Features** table rewritten to what is live; every row checked against STATUS §1 and DESIGN.
   No "† in progress" footnotes remain.
3. **How it works** caption and **Responsible AI** lose the in-progress notes; Responsible AI
   gains: transcripts made from the public recording only, with nothing about the reader; the
   extension's redaction and refusals (README's own words from the install section).
4. **How Gen AI** adds `transcribe` and the judge route; models from `deploy.env.yaml`.
5. **Evaluation** adds the safety evals row (latest run, judge disclosed) and keeps every existing
   number as is (decision 57: 64% / 13% beside 89% / 66% and all three precision numbers stay).
6. **Where we are + Roadmap** merged into one short "Status" section: what is live (by
   milestone, linking STATUS), what was measured and missed (frozen-graph linking targets),
   honest limits (English only; videos ≤ 10 min, podcasts ≤ 12; the extension is unpacked, Chrome
   only; demo caps). Roadmap checkboxes all reflect STATUS §1.
7. **Architecture**: `media` box in the API, the extension as a second client; Repository
   structure updated.
8. **Getting started**: `.gcp.local.mk` for `ACCOUNT`.
9. **Team**: ask Sourabh for names and links; until he answers, the section is removed rather
   than left as a placeholder (it returns when he gives the details).

## Checks
- Every number in the README appears in STATUS, an eval report or `deploy.env.yaml` (a reviewer
  pass checks each against its source).
- Every relative link and image path resolves (a small script: each `](path)` and `src="path"`
  exists in the tree; anchors match headings).
- No account address or name of the project account (`git grep -i` for the local part, typed on
  the command line only).
- Rendered check: GitHub's markdown API (`gh api markdown`) renders without error; images load from
  the branch on GitHub after push.

## Acceptance
Plan-reviewer APPROVE → edit → checks above → milestone-reviewer SHIP → PR → CI → merge. Nothing
to deploy.
