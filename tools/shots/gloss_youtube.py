"""Decision 62 local check (plan R7): Open in Gloss in the built extension, spending nothing.

No web app runs (the script refuses to start if port 5173 answers), so the reader tab it opens
loads nothing and calls nothing. Every worker request to the API is paused at the request stage
by CDP Fetch and answered in the browser, so it never reaches port 8000 even if a dev API is up:
nothing can reach a model, a search or Firestore. The extension's emulator build runs in Chrome
for Testing (m8's launch); a demo session is written straight into its session storage; the
YouTube page is a stub served at the real watch URL through CDP Fetch on the page; the worker's
POST /v1/recs/open is answered by CDP Fetch with a fixed reply, and any other API request gets a
404 and fails the check.

    pnpm --filter extension build:emulator
    SHOTS_OUT=docs/evidence/gloss-address uv run --project apps/api python tools/shots/gloss_youtube.py
"""

import asyncio
import base64
import json
import socket
import sys
import urllib.request

import websockets

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
import m8  # noqa: E402
from m8 import EXT_ID, Harness, attach, launch, record, results, step, targets  # noqa: E402

WATCH = "https://www.youtube.com/watch?v=wajoP_5Cpw8"
TAB_URL = WATCH + "&t=42s&si=track&list=PL1"  # what the reader's tab says; only WATCH may be sent
ARTICLE = "https://news.gloss-test.example/story"
CONTENT_ID = "93053af2e368625142213283d9abe557"  # the Fireship video's production id (R7 of decision 61)
WEB = "http://localhost:5173"  # the emulator build's web base
API = "http://127.0.0.1:8000"
TOO_LONG = ("Too long for Gloss for now: videos up to 10 minutes, podcasts up to 12. "
            "Use “Open original” to watch or listen on the publisher's site.")
STUB = {
    "www.youtube.com": "<!doctype html><title>Stub video</title><h1>A stub YouTube watch page</h1>",
    "news.gloss-test.example": "<!doctype html><title>Story</title><article><h1>Story</h1>"
    + "<p>A paragraph of a stub article for the popup's article view.</p>" * 6 + "</article>",
}
POPUP_CLOSED = "(popup closed: the new tab took focus)"
SESSION_JS = """chrome.storage.session.set({session: {
  idToken: 'h.' + btoa(JSON.stringify({firebase: {sign_in_provider: 'anonymous'}})) + '.s',
  refreshToken: 'r', expiresAt: Date.now() + 3600e3, apiKey: 'k', persona: 'trader', density: 'balanced'}}).then(() => 1)"""
POPUP_JS = """({video: !document.getElementById('video-actions').hidden,
  article: !document.getElementById('article-actions').hidden,
  focused: document.activeElement && document.activeElement.id,
  button: document.getElementById('open-video').textContent,
  hint: document.getElementById('video-hint').textContent})"""


class Routed(m8.Session):
    """A CDP target whose paused requests go to `route` (Fetch at the request stage)."""

    def __init__(self, ws, route):
        super().__init__(ws)
        self.route = route
        self.seen: list[dict] = []

    async def _loop(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
            elif msg.get("method") == "Fetch.requestPaused":
                asyncio.get_running_loop().create_task(self._answer(msg["params"]))
            elif "method" in msg:
                self.events.append(msg)

    async def _answer(self, params):
        req = params["request"]
        self.seen.append({"method": req["method"], "url": req["url"], "body": req.get("postData")})
        status, body, kind = self.route(req)
        # CORS as the API answers it: the worker sends Authorization, so a preflight comes first.
        cors = [{"name": "Access-Control-Allow-Origin", "value": "*"},
                {"name": "Access-Control-Allow-Methods", "value": "GET, POST, PUT, PATCH, DELETE"},
                {"name": "Access-Control-Allow-Headers", "value": "Authorization, Content-Type, Accept"}]
        await self.send("Fetch.fulfillRequest", requestId=params["requestId"], responseCode=status,
                        responseHeaders=[{"name": "Content-Type", "value": kind}, *cors],
                        body=base64.b64encode(body.encode()).decode())


def page_route(req):
    host = req["url"].split("/")[2]
    return 200, STUB.get(host, ""), "text/html; charset=utf-8"


api_reply = {"status": 200, "body": {"content_id": CONTENT_ID}}


def api_route(req):
    if req["method"] == "OPTIONS":
        return 204, "", "text/plain"
    if req["method"] == "POST" and req["url"] == f"{API}/v1/recs/open":
        return api_reply["status"], json.dumps(api_reply["body"]), "application/json"
    return 404, json.dumps({"error": "not_routed", "message": "not routed in this check"}), "application/json"


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


async def press(h: Harness, shot: str | None = None) -> tuple[dict, str]:
    pop = await h.popup()
    view = await pop.eval(POPUP_JS)
    if shot:
        print(f"[{shot}]", await pop.shot(shot))
    message = ""
    if view["video"]:
        await pop.eval("document.getElementById('open-video').click(); 1")
        try:
            for _ in range(40):
                message = await pop.eval("document.getElementById('message').textContent")
                if message and message != "Opening this video in Gloss…":
                    break
                await asyncio.sleep(0.25)
        except websockets.exceptions.ConnectionClosed:
            # Chrome closes a popup when the tab it opens takes focus: the success path.
            return view, POPUP_CLOSED
    await h.close(pop)
    return view, message


async def main() -> None:
    if port_open(5173):
        raise SystemExit("refusing to run: a web app answers on 5173; the reader tab must load nothing")
    launch()
    version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{m8.PORT}/json/version").read())
    browser = await attach(version["webSocketDebuggerUrl"])
    created = (await browser.send("Target.createTarget", url="about:blank"))["targetId"]
    await asyncio.sleep(1)
    first = next(t for t in targets() if t["id"] == created)
    page = Routed(await websockets.connect(first["webSocketDebuggerUrl"], max_size=50_000_000), page_route)
    await page.send("Page.enable")
    await page.send("Runtime.enable")
    await page.send("Fetch.enable", patterns=[{"urlPattern": f"https://{h}/*"} for h in STUB])
    sw = None
    for _ in range(40):
        sw = next((t for t in targets() if t["url"].startswith(f"chrome-extension://{EXT_ID}/")
                   and t["type"] == "service_worker"), None)
        if sw:
            break
        await asyncio.sleep(0.25)
    worker = Routed(await websockets.connect(sw["webSocketDebuggerUrl"], max_size=50_000_000), api_route)
    await worker.send("Runtime.enable")
    await worker.send("Fetch.enable", patterns=[{"urlPattern": f"{API}/*"}])
    h = Harness(browser, page, created, worker)
    record("browser", version["Browser"])
    record("session written", await worker.eval(SESSION_JS))
    failures: list[str] = []
    try:
        step("youtube: Open in Gloss")
        await h.goto(TAB_URL, wait=2)
        view, message = await press(h, "popup-youtube")
        tabs = sorted({t["url"] for t in targets() if t["url"].startswith(WEB)})
        record("youtube popup", view)
        record("youtube message", message)
        sent = [{**r, "body": json.loads(r["body"]) if r["body"] else None}
                for r in worker.seen if r["method"] != "OPTIONS"]
        record("api requests", sent)
        record("tabs opened", tabs)
        if not (view["video"] and not view["article"] and view["focused"] == "open-video"):
            failures.append("popup did not show Open in Gloss (focused) on a YouTube video")
        if sent != [{"method": "POST", "url": f"{API}/v1/recs/open", "body": {"url": WATCH}}]:
            failures.append("the worker sent something other than one POST /v1/recs/open with the canonical URL")
        if tabs != [f"{WEB}/read/{CONTENT_ID}?persona=trader"]:
            failures.append("the reader tab is not /read/<id>?persona=trader on the web base")
        if message not in ("Opened in a new tab.", POPUP_CLOSED):
            failures.append(f"unexpected popup message: {message!r}")

        # The reader tab took focus; close it so the YouTube tab is the active one again.
        for t in targets():
            if t["url"].startswith(WEB):
                await browser.send("Target.closeTarget", targetId=t["id"])
        await browser.send("Target.activateTarget", targetId=created)
        await asyncio.sleep(0.5)

        step("youtube: a refusal")
        api_reply.update(status=422, body={"error": "too_long", "message": TOO_LONG})
        worker.seen.clear()
        _, refused = await press(h, "popup-youtube-too-long")
        record("refusal message", refused)
        if refused != TOO_LONG.split(" Use “Open original”")[0]:
            failures.append(f"refusal shown as {refused!r}")

        step("article: Read this page unchanged")
        worker.seen.clear()
        await h.goto(ARTICLE, wait=2)
        view, _ = await press(h, "popup-article")
        record("article popup", view)
        if not (view["article"] and not view["video"] and view["focused"] == "read"):
            failures.append("popup on an article did not show Read this page")

        every = [r["url"] for r in worker.seen] + [r["url"] for r in page.seen]
        spenders = [u for u in every if "/transcribe" in u or "/analyse" in u or "/explain" in u]
        record("model routes requested", spenders)
        if spenders:
            failures.append("a model route was requested")
    finally:
        record("failures", failures)
        cdp.OUT.mkdir(parents=True, exist_ok=True)
        (cdp.OUT / "youtube-local.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
        await browser.send("Browser.close")
    if failures:
        raise SystemExit(1)
    print("all pass")


if __name__ == "__main__":
    asyncio.run(main())
