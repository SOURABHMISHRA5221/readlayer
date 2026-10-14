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
- Team is a placeholder table (kept on Sourabh's answer, item 9).

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
9. **Team**: unchanged, placeholder kept (Sourabh, 2026-10-14: "Keep it placeholder").

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

## Round 1 (plan-reviewer REVISE 9; applied, these override the sections above)

**R1. Alt texts true to the raw stills.** The device frames are CSS (`DeviceFrame.tsx`); the stills
are bare windows. From the landing's alts drop "on a monitor" (`shot-feed`), "on a laptop"
(`shot-reader`), "in Chrome" (`shot-extension`); the rest verbatim. `shot-phone` (390×844) in an
`<img width="…">`. An HTML comment beside the image block says the paths track the landing stills,
so a rename there reruns the link check. The feed still's "prepared in advance … 11 Oct" line is
accepted (a retake needs a demo reader; not after the freeze).

**R2. Install steps match the landing** (`landing/Extension.tsx`, STATUS §9 Oct 16): four steps,
pinning inside step 2 (puzzle-piece menu); the build-it-yourself route and Open in Gloss on YouTube
as notes after the steps.

**R3. Counts dated or refreshed; decision 57 untouched.** Item 5's "unchanged" covers the decision-57
linking numbers and dated measurements only. Library: 323 library pages analysed (ops report); the
"8 of 310" overlap labelled as the Oct 5 measurement on the 310 corpus articles (STATUS §12).
Concept graph: 5,206 seeded, 5,281 served on Oct 14 (STATUS §29).

**R4. How Gen AI complete.** Add `restate` (MODEL_QUALITY, its own task since explain-v4),
`profile_edit` (MODEL_FAST, Gemma fallback: edit-by-prompt and Describe yourself only; the
`link_confirm` and `embed` rows also say they match the reader's redacted onboarding pieces and goal
phrases, one piece per call, DESIGN §11.4 and §18),
`concept_jurisdiction` in the graph row, `transcribe` (MODEL_QUALITY), and `landing_art`
(MODEL_IMAGE) named as offline, one-off (landing illustrations), never at runtime. The judge for
`verify` / `verify_background` is MODEL_JUDGE, unset in production, so Gemini 3.8 Flash.

**R5. The privacy sentence, true.** "Models get article and concept content and, for profile edits,
goals and onboarding, the reader's own words with emails, phone and card numbers removed first;
never user ids, emails or reading history. Search providers get concept and topic labels (and fixed
phrases), never anything the reader typed." Checked against DESIGN §11 (free-text exception,
decision 42: onboarding text never reaches search, a log or a stored document) and §11.3.

**R6. Limits as enforced.** "Built and evaluated on English; videos and podcasts must be English
(others are refused)". Extension: "loaded unpacked in Chrome, not on the Chrome Web Store; other
Chromium browsers untested". Media: transcripts are made automatically and can contain errors; the
recording is the source (`WatchListen.tsx`). Caps the README states, from `config.py` defaults (not
overridden in `deploy.env.yaml`) and `deploy.env.yaml`: new links 20 a day per reader, 3 per demo
reader; videos and podcasts 5 a day per reader, 1 per demo reader; videos ≤ 10 min, podcasts ≤ 12;
LLM budget $8 a day. Shared demo caps mentioned without numbers.

**R7. Sources for numbers** add `apps/api/app/config.py` and DESIGN §11.5.

**R8. Getting started for outsiders:** edit `PROJECT` and `REGION` in the Makefile and create
`.gcp.local.mk` with `ACCOUNT := you@example.com` (gitignored); the Makefile's error message is
changed to name the README section as well as CLAUDE.local.md (a one-line Makefile text change; no
behaviour change).

**R9. Safety evals row:** run of Oct 10 on the live prompts (restate-v2, explain-v5, verify-v2,
verify-background-v1), judge Gemini 3.8 Flash: adversarial 15/15 rejected, good 24/25 accepted
(G21 rejected), injection 10/10 safe, Background suite 3/3 rejected and 2/2 accepted, non-business
6/7 (outside the M5 targets). Link `apps/api/evals/report.md`.

**Round 2** (plan-reviewer REVISE 1): R4's `profile_edit` row corrected (onboarding text and goals
go through `embed` and `link_confirm` as redacted pieces, not `profile_edit`). Applied above.

**Approved** (plan-reviewer round 3, 2026-10-14, at 7e9ef86).
