# A "gloss" web address, Open in Gloss on YouTube, repo public (decision 62, 2026-10-15)

Sourabh, 2026-10-14: "can we get domain gloss instead of readlayer?", then "lets push new domain
for tomorrow"; "yes" to an "Open in Gloss" button on YouTube video pages in the same extension
release; "lets add Repo go live to in this". Branch `gloss-address` from `main` (527d569).
Scheduled Oct 15, before the Oct 16 freeze; checkpoint: not merged by end of Oct 15 IST → ask
Sourabh what to cut (decision 27).

## Facts this plan rests on (checked 2026-10-14)
- Hosting is one site (`firebase.json` `hosting` object, `.firebaserc` default project).
  `https://gloss.web.app`, `gloss-reader`, `glossreader`, `readgloss` all answer Firebase's
  "Site Not Found" page; whether an id is free is only known when `hosting:sites:create` runs.
- The old address is hard-coded in: `apps/api/deploy.env.yaml` `CORS_ORIGINS`,
  `apps/extension/.env.production` (`VITE_WEB_BASE`, `VITE_WEB_ORIGINS`, which also
  build the manifest's `externally_connectable`), `README.md` (2 links), and six `tools/shots/*`
  scripts. Tests use `readlayer.web.app` as a dummy and need no change.
- Web sign-in is `signInWithPopup` with `authDomain` `readlayer-sourabh-26.firebaseapp.com`; a
  popup from another origin works once that origin is an Auth authorized domain. The OAuth
  redirect stays on the old `firebaseapp.com` handler, so **no OAuth client change**; the Google
  account chooser keeps saying "continue to readlayer-sourabh-26.firebaseapp.com" (see Open).
- Only extension-read pages are private (`content/access.py` `PRIVATE_SOURCES = {"extension"}`);
  pasted links and recordings open for any reader by id. Sign-in state is per origin, so the
  extension still opens the web reader on the origin its session came from: the reader lands as
  the same uid that opened the video (it joins that uid's library, `?persona=` applies to that
  anonymous user), not as another session or a signed-out landing (R1).
- The web's Connect page shows "The extension isn't installed in this browser yet" when the
  extension doesn't list the page's origin, which is what 0.8.1 will do on the new address.
- Web main bundle 149.88 KB gzip, budget 150.00 KB: **this plan changes nothing in main**
  (landing links and the Connect page are lazy chunks). Measured before and after anyway.
- gitleaks is not installed. Tracked files hold no secrets found by a quick email/name scan, but
  the project's dedicated Google account email is in the `Makefile` (`ACCOUNT`), STATUS and
  AUTOPILOT_LOG, and in history (R5).
  Every commit on every branch has a GitHub noreply author and committer address. No employer name in the tree.

## What changes

**A. A second Hosting site, same build.** Site id: `gloss` if free, else `gloss-reader`, else
`glossreader` (first one `hosting:sites:create` accepts; the rest of the plan says `<gloss>`).
`firebase.json` `hosting` becomes an array of two entries with targets `app`
(`readlayer-sourabh-26`) and `gloss` (`<gloss>`), the same public dir, rewrites and headers
(one JSON block duplicated; a small test asserts the two entries are identical apart from
`target`). `.firebaserc` gains the `targets` map (committed; `firebase target:apply`).
`make deploy-web` keeps `firebase deploy --only hosting`, which deploys both. The old address
keeps serving the same build: 0.8.1 installs, judge links and README history keep working.
No redirect between them.

**B. Origins.** `deploy.env.yaml` `CORS_ORIGINS` gains
`https://<gloss>.web.app,https://<gloss>.firebaseapp.com` (old ones kept). Auth authorized
domains gain `<gloss>.web.app` and `<gloss>.firebaseapp.com` (Identity Toolkit admin v2
`projects/readlayer-sourabh-26/config`, PATCH with `updateMask=authorizedDomains`, after a GET
whose list is printed before and after; nothing removed). A pytest asserts every
`deploy.env.yaml` origin is either `chrome-extension://<EXTENSION_ID>` or a site in
`.firebaserc`'s targets (so a Hosting site can't miss CORS).

**C. Extension 0.8.2.**
- `.env.production`: `VITE_WEB_BASE=https://<gloss>.web.app`; `VITE_WEB_ORIGINS` = the four
  origins (new two first). The manifest's `externally_connectable` follows (existing build).
  Version 0.8.2 in `manifest.base.json` and `package.json`.
- **Session origin.** `onExternal` "connect" stores the caller's origin in the session
  (`webOrigin`, only if it is in `WEB_ORIGINS`, which it already checks). A new `webBase(session)`
  returns it, else `WEB_BASE` (sessions saved by 0.8.1 have none). Used by the popup's links
  (profile, connect, setup), the overlay's links (the `start({ webBase })` argument), and C3.
- **Open in Gloss on YouTube.** New `src/youtube.ts`: `youtubeWatchUrl(url)` returns
  `https://www.youtube.com/watch?v=<id>` for the same links the API's `media/urls.py`
  `_youtube_id` accepts (www/m/no-www `watch?v=`, `shorts/<id>`, `embed/<id>`, `youtu.be/<id>`,
  11-char id), else null. Only the canonical URL is ever sent: no playlist, time, `si` or other
  parameters. Cases come from one shared fixture, `apps/api/tests/fixtures/youtube_urls.json`
  (url → id or null), read by both a new vitest and the existing pytest, so the two can't drift.
- Popup: on load it reads the active tab's URL (already granted by activeTab when the popup is
  opened from the toolbar). On a YouTube video, "Read this page" is replaced by **"Open in
  Gloss"** with the hint "Opens this video in Gloss with a transcript and notes. Up to 10
  minutes." (cap from the same 600 s; the extension test reads `deploy.env.yaml` as the landing
  test does). Clicking sends `{ type: "open-video", tabId }` to the worker; the worker re-reads
  the tab URL itself (never trusts a URL from the popup), maps it with `youtubeWatchUrl`, calls
  `POST /v1/recs/open` with `{ url }` through the existing `call()` (token refresh included), and
  on success opens a new tab at `${webBase(session)}/read/<content_id>` plus `?persona=<key>` for
  a demo session (the web's `personaParam` format). On an API refusal the popup shows the API's
  `detail` (the existing media refusal messages: too long, media off, daily cap); offline or other
  errors: "Gloss couldn't open this video. Try again, or paste the link in Gloss." Signed out:
  the existing Connect view. Not connected to a video page that isn't YouTube: unchanged.
- Permissions unchanged (activeTab, scripting, storage); `check-manifest.mjs` passes as is.
  No new message type from content scripts or the web; `open-video` is accepted only from the
  popup (`fromPopup`). Redaction: the only thing sent is the canonical watch URL (no page text),
  so `redact.ts` isn't involved; the test asserts nothing but that URL is in the request body.

**D. Web (lazy chunks only).**
- `landing/links.ts`: `EXTENSION_RELEASE_URL` → `releases/tag/extension-v0.8.2`; the landing's
  "v0.8.1" button text and its render test move with it (STATUS §5 risk). The extension still
  stays (0.8.1 on Yield curve; the popup looks the same apart from the hidden version) and its alt
  text names no version; checked, else the alt drops the version.
- Connect page, "missing" view: one more line: "Installed Gloss 0.8.1 before <date>? It connects
  from readlayer-sourabh-26.web.app; get 0.8.2 to connect here." with the release link, shown only
  when `window.location.hostname` isn't the old host. Render test for both hosts.
- `landing/links.ts` comment about the private repo goes once the repo is public (F).

**E. Links and docs.** README's two live links → `https://<gloss>.web.app` (the old address named
once as also working); install steps say 0.8.2 and mention Open in Gloss on YouTube. The six
`tools/shots` scripts get one `WEB` constant from a shared `tools/shots/site.py`, set to the new
address (old scripts that recorded evidence still run). DESIGN §20.2 and a new short §22
(addresses, session origin, Open in Gloss); STATUS decision 62 row, §1, §5 risks (release pin
closed, private-repo 404 closed after F), an acceptance section; AUTOPILOT_LOG.

**F. Repo public.**
1. `brew install gitleaks`; `gitleaks git --redact --report-path <scratch>/gitleaks.json` over
   the full history of all branches, plus `gitleaks dir` on the tracked tree. `git ls-files`
   confirms no `.env`, `.env.local` or key file is tracked (they stay gitignored).
2. Every finding is classified: a test fixture or public value (Firebase web API key, the
   extension's public `key`, the Cloud Run URL) → allow-listed in `.gitleaksignore` with a reason;
   a real secret → rotated first (Secret Manager new version, old disabled), then reported to
   Sourabh before going public. No history rewrite unless Sourabh asks.
3. A short manual check gitleaks doesn't do: `git grep` for emails and personal names in tracked
   files and in `git log --all -p` subject lines; the result goes to Sourabh (see Open on the
   `Makefile` email).
4. On Sourabh's yes: `gh repo edit --visibility public --accept-visibility-change-consequences`.
   Then, signed out (a fresh browser context): the landing's GitHub link, the 0.8.2 release page
   and its zip download answer 200; the README renders.

## Order of the outward steps (each on Sourabh's yes, `make check-gcp` before every cloud one)
1. PR → CI → milestone-reviewer SHIP → merge (code reaches `main` first; nothing deployed yet).
2. `firebase hosting:sites:create <gloss>`, `firebase target:apply` (if the id differs from
   `gloss`, a one-line commit before step 5 fixes `.firebaserc`, `.env.production`,
   `deploy.env.yaml`, README).
3. Auth authorized domains PATCH (printed before/after).
4. `make deploy-api` (env only: CORS). Check: a preflight from `https://<gloss>.web.app` gets
   `access-control-allow-origin`; the old origin still does.
5. `make extension-zip`, `gh release create extension-v0.8.2` with the zip (release notes: new
   address, Open in Gloss on YouTube).
6. `make deploy-web` from clean `main`: both sites.
7. gitleaks (F1–F3 run earlier, during the build; only the visibility change waits here), then
   repo public, then the signed-out link checks.

## Production writes, at most
1 Hosting site; 2 authorized domains added; 1 API revision (env only); 1 web deploy (2 sites);
1 GitHub release; visibility change. Live check readers: **1 anonymous demo reader** for C
(open one stored short video, the Fireship `wajoP_5Cpw8`, already in production: `open_media`
returns early for a stored recording, so no transcript, no slot, no LLM call; its notes are
cached), deleted with DELETE /v1/me and confirmed gone. Plus Sourabh's own Google sign-in on the
new address, done by him. 0 new `contents/` docs, 0 generations, 0 searches.

## Tests (first)
- Extension: `youtube.test.ts` (shared fixture); `background.test.ts`: connect stores
  `webOrigin` only for allowed origins; `webBase` fallback; `open-video` from the popup only,
  re-reads the tab, sends only the canonical URL, opens `/read/<id>` on the session's origin with
  `?persona=` for demo, surfaces the API `detail` on refusal; a test that `.env.production`'s
  origins include the base and that the built manifest's `externally_connectable` lists all four.
- API: `test_media_urls.py` reads the shared fixture; `test_cors.py` (or a new
  `test_deploy_env.py`): `deploy.env.yaml` origins ⊆ `.firebaserc` sites (both domains) + the
  extension.
- Web: links render test (0.8.2 href and text); Connect page hint on the new host only;
  `firebase.json` entries identical apart from `target`.

## Acceptance
1. `pnpm -r typecheck`, `pnpm -r test`, `uv run pytest -q`, ruff; extension build passes the
   manifest check; main ≤ 150.00 KB gzip (unchanged).
2. Local: the built 0.8.2 against the emulators (`build:emulator`) on a YouTube watch page: Open
   in Gloss shows, sends one `/v1/recs/open` with the canonical URL; on an article "Read this
   page" is unchanged (the existing harness, if it covers the popup; else a Playwright step).
3. Live: the new address loads (landing, axe 0 at 1440 and 390); Google sign-in works there
   (Sourabh); demo sign-in → Connect from the new address with 0.8.2 → on the Fireship YouTube
   page, Open in Gloss opens `<gloss>.web.app/read/93053af2…` with the transcript and notes;
   the old address still loads and its Connect works with 0.8.1 (as today). Demo reader deleted.
4. gitleaks: 0 unexplained findings; repo public; signed-out GitHub link, release page and zip
   download 200.

## Cuts (in order, if Oct 15 runs short)
D's Connect line, then the shared `tools/shots/site.py` (scripts keep the old address, which
still works), then Open in Gloss (0.8.2 ships with the address only). Never: CORS, Auth domains,
the landing pin moving with the release, gitleaks before public.

## Open (for Sourabh)
1. Google's account chooser will still say "continue to readlayer-sourabh-26.firebaseapp.com" on
   the new address. Changing that needs `authDomain` per site and a new redirect URI on the OAuth
   client in the Cloud console (by hand). Default: leave it.
2. The `Makefile` names the project's Google account email, and history has it. It isn't a
   secret, but going public publishes it. Default: replace it in the tree with a value read from
   a gitignored file, no history rewrite.

## Round 1 (plan-reviewer REVISE, 9 items; applied, these override the sections above)

**R1. Why the session origin.** Facts corrected (only `extension` docs are private). `webOrigin`
stays for: same uid on the web as the one that opened the video, the video in that uid's library,
`?persona=` for that anonymous user. No test or DESIGN text claims a 404 from another origin.

**R2. Refusals in the popup by code.** `/v1/recs/open` refusals are `{error, message}` (`_error`
in `ingest/router.py`), surfaced by `call()` as `ApiReply.message`, and end with "Use “Open
original”…", meaningless in the popup. The worker maps `error` to popup copy: `too_long` ("This
video is over 10 minutes; Gloss opens videos up to 10."), `media_off` ("Gloss isn't opening
videos right now."), `media_cap_reached` and the daily-budget code ("Gloss has opened its share
of videos for today. Try again tomorrow."), `media_unavailable` and anything else ("Gloss
couldn't open this video. Try again, or paste the link in Gloss."). Exact codes read from
`media/refusals.py` and the router at build time; one `background.test.ts` case each. Demo
persona: `session.persona ?? "newcomer"`. The `onboarded()` gate of `readTab` applies to
`open-video` too (same "Finish setting up" view).

**R3. Site id known before the build.** Outward step 2 moves first: on Sourabh's yes, after
`make check-gcp`, `firebase hosting:sites:create` (gloss → gloss-reader → glossreader) runs before
any code, so the real id is in `.firebaserc`, `.env.production`, `deploy.env.yaml` and README
inside the PR. Anything found after merge goes in a follow-up PR with CI green, never a direct
commit to `main`.

**R4. Scan everything that goes public.** Before scanning: `git fetch origin
'+refs/pull/*/head:refs/remotes/origin/pr/*'` (local, read only; 37 PR heads, 8 not reachable
from any branch). Then `gitleaks git --log-opts="--all" --redact`; the log records the number of
commits scanned and that it equals `git rev-list --all --count`.

**R5. The email, everywhere.** Open 2's default covers every tracked file (Makefile, STATUS,
AUTOPILOT_LOG): replaced by a value from a gitignored file (Makefile) or "the project's Google
account" (docs). History keeps it unless Sourabh asks for a rewrite; said plainly to him. F3 also
checks PR and issue titles and bodies (public with the repo); the reviewer's check found it in
none of the 37 PRs, re-run at F3 time and recorded.

**R6. Live-check bounds, honest.** The reader page calls `/content/{id}/recommendations`, which
can search (Tavily / YouTube) for stale concept caches within the anonymous allowance
(`anonymous_allowance_left()`). Bound: searches ≤ `WEB_TRIGGERS` × formats for that one page,
within the anonymous allowance. Generations: the precheck (`landing_media_precheck` style, read
only) names the persona (newcomer) and the note whose explanation is cached and verified, both
parts, on the Fireship doc; the check opens only that note; afterwards the API revision logs show
0 `explain` generations in the check window (logged).

**R7. Local check, no spend.** Script `tools/shots/gloss_youtube.py` (from `m8_live.py`): the
emulator build of 0.8.2, a Playwright route fulfils `POST /v1/recs/open` with a fixed
`{content_id}` and a stub YouTube watch page is served locally; asserts the popup shows Open in
Gloss, the request body is exactly the canonical URL, a tab opens at `<web>/read/<id>`, and no
`/transcribe` or `/analyse` request is made (the `/read` tab's API calls are routed to 404 stubs).
On a stub article page, "Read this page" is unchanged.

**R8. Auth domains dry run.** Before the PATCH: print the GET list, the exact body (GET list + the
two new domains) and the diff; abort if any existing domain is missing from the body
(`updateMask=authorizedDomains` replaces the list). Print the GET again after.

**R9. The API deploy ships no code.** Before `make deploy-api`:
`git diff 615d676 main -- apps/api/app apps/api/pyproject.toml apps/api/uv.lock apps/api/Dockerfile`
must be empty (it is today; this PR touches only tests and `deploy.env.yaml` under `apps/api`).
If not empty, stop and list what ships.

Nits taken: the `Makefile`'s unused `HOSTING` line is left alone. The Cuts list is the
proposal put to Sourabh at the checkpoint, not applied by itself (STATUS §9).

**Approved** (plan-reviewer round 2, 2026-10-14). Nits taken: R7's stub YouTube page is served at
the real URL `https://www.youtube.com/watch?v=wajoP_5Cpw8` through a Playwright route (a localhost
URL would make `youtubeWatchUrl` return null); `HOSTING` dropped from the Facts.

## Round 2 (Sourabh's answers, 2026-10-14; these override the sections above)

Sourabh: "Yes on 1, No on 2, 3 yes".

**R10. Site created: `glossreader`.** `gloss` and `gloss-reader` are reserved by other projects
(Hosting API 400). `hosting:sites:create glossreader` succeeded: `https://glossreader.web.app`.
Every `<gloss>` above is `glossreader`. `/__/auth/handler` already answers 200 there.

**R11. Sign-in names Gloss, not readlayer (Open 1 answered "no": change it).**
- Web: on `glossreader.web.app` the Firebase `authDomain` is that host (same origin as the app),
  else the built `VITE_FIREBASE_AUTH_DOMAIN` as today. One `GLOSS_HOST` constant in a new tiny
  `lib/sites.ts` (also used by the Connect page hint, lazy), read in `lib/auth.ts`. This is the
  one main-bundle change: **gate main ≤ 150.00 KB gzip**, measured before and after; if over,
  something else in main pays for it (named in the PR) or Sourabh is asked. `glossreader.firebaseapp.com`
  keeps the old `authDomain` (no redirect URI for it). Same-origin `authDomain` also takes the
  popup off the cross-site iframe that browsers' storage partitioning can break.
- Sourabh, by hand in the Cloud console, **before the web deploy** (a web deploy without it gives
  `redirect_uri_mismatch` on the new address): APIs & Services → Credentials → the OAuth client
  "Web client (auto created by Google Service)": add Authorized JavaScript origin
  `https://glossreader.web.app` and redirect URI `https://glossreader.web.app/__/auth/handler`;
  nothing removed. Branding (OAuth consent screen): if the app name says readlayer, set it to
  "Gloss" (shown on both addresses). The CLI can't read the brand (IAP OAuth Admin API is off and
  being shut down), so he reports what it said.
- Unit test: `authDomain` for `glossreader.web.app`, `readlayer-sourabh-26.web.app`,
  `glossreader.firebaseapp.com` and the emulator.
- Acceptance 3 gains: Sourabh signs in with Google on `glossreader.web.app`; the account chooser
  names glossreader.web.app or Gloss, not readlayer; sign-in on the old address still works.
- Outward order: the console step goes between the Auth domains PATCH (3) and the API deploy (4).

**R12. The Gmail address leaves tracked files (Open 2 answered "yes"), history kept.** `Makefile`:
`ACCOUNT` comes from `-include .gcp.local.mk` (gitignored, written once from CLAUDE.local.md);
`check-gcp` fails with "ACCOUNT unset: create .gcp.local.mk (see CLAUDE.local.md)" when it's
missing. STATUS and AUTOPILOT_LOG say "the project's Google account" instead. A `git grep` for
the address returns nothing before the PR. History keeps it (Sourabh's choice).

## Round 3 (plan-reviewer REVISE 3 on round 2; applied, these override the sections above)

**R13. The new site's Firebase config before sign-in.** `https://glossreader.web.app/__/firebase/init.json`
answers 404 today (the default site: 200). Right after the web deploy and before Sourabh tries
Google sign-in there: `curl` it; it must be 200 with `projectId` `readlayer-sourabh-26` and the
build's `apiKey`. If not: link the site to the `readlayer-web` web app (Hosting console or the
Firebase REST call, on Sourabh's yes) and check again. Fallback if Google sign-in still fails on
glossreader: a follow-up PR (CI green) makes that host use the built `authDomain` again, web
redeployed; the old address is never affected.

**R14. `.gcp.local.mk` gitignored, done.** `.gitignore` lists it; `git check-ignore` passed before
the file was written; `make check-gcp` passes with it and fails with "ACCOUNT unset…" without it.

**R15. The name, not just the address.** The check is `git grep -n -i sourabhlocalllm` returning
nothing: done (Makefile, STATUS §-identity line, both AUTOPILOT_LOG lines rewritten).

Optional taken: if the consent screen wants brand verification to rename it, the rename is
skipped (the chooser then names glossreader.web.app, which meets acceptance 3) and what the screen
said is recorded. The host → `authDomain` choice is a pure `authDomainFor(hostname, built,
emulator)` in `lib/sites.ts`, unit-tested without importing `auth.ts`.

R4/R5 results (2026-10-14): 37 PR heads fetched; `gitleaks git --log-opts=--all` scanned 446 of
448 commits (the other two carry no diff of their own); 2 findings, both the extension manifest's
public RSA key (allow-listed in `.gitleaksignore` with the reason), rescan clean. No email address
in the 37 PR titles and bodies or the 1 issue.
