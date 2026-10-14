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
- The old address is hard-coded in: `apps/api/deploy.env.yaml` `CORS_ORIGINS`, `Makefile`
  `HOSTING`, `apps/extension/.env.production` (`VITE_WEB_BASE`, `VITE_WEB_ORIGINS`, which also
  build the manifest's `externally_connectable`), `README.md` (2 links), and six `tools/shots/*`
  scripts. Tests use `readlayer.web.app` as a dummy and need no change.
- Web sign-in is `signInWithPopup` with `authDomain` `readlayer-sourabh-26.firebaseapp.com`; a
  popup from another origin works once that origin is an Auth authorized domain. The OAuth
  redirect stays on the old `firebaseapp.com` handler, so **no OAuth client change**; the Google
  account chooser keeps saying "continue to readlayer-sourabh-26.firebaseapp.com" (see Open).
- Private docs (pasted links, recordings) are readable only by the reader who brought them in
  (`content/access.py`). Sign-in state is per origin. So the extension must open the web reader
  on the origin its session came from, or the reader sees another session (or none) and a 404.
- The web's Connect page shows "The extension isn't installed in this browser yet" when the
  extension doesn't list the page's origin, which is what 0.8.1 will do on the new address.
- Web main bundle 149.88 KB gzip, budget 150.00 KB: **this plan changes nothing in main**
  (landing links and the Connect page are lazy chunks). Measured before and after anyway.
- gitleaks is not installed. Tracked files hold no secrets found by a quick email/name scan, but
  the `Makefile` holds the project's dedicated Google account email (`ACCOUNT`), in history too.
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

**B. Origins.** `Makefile` `HOSTING` and `deploy.env.yaml` `CORS_ORIGINS` gain
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
