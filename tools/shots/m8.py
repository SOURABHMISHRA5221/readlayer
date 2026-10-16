"""M8-local acceptance on the emulator harness (docs/plans/M8.md, acceptance 1–8): the Gloss
extension in headless Chrome for Testing, driven over CDP. Emulators only (the extension's
emulator build calls the local API); live news pages are fetched by the browser and ingested into
the emulator. The click is CDP Extensions.triggerAction on the tab, which grants activeTab exactly
like a toolbar click; the harness then presses the popup's "Read this page".

    make dev-emulator                                  # in another terminal
    pnpm --filter extension build:emulator
    SHOTS_OUT=docs/evidence/m8 uv run --project apps/api python tools/shots/m8.py

Branded Google Chrome ignores --load-extension since Chrome 137, so this uses Playwright's Chrome
for Testing build. Local fixture pages are served on 127.0.0.1 behind a public-looking host
(--host-resolver-rules), since the extension refuses private hosts and the API takes ports 80/443.
"""

import asyncio
import glob
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import websockets

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
from onboarding import tick, type_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EXT_DIR = ROOT / "apps" / "extension" / "dist"
EXT_ID = "lnfamfbeffepopbmedfenfmgljoacbmg"
W = "http://localhost:5173"
API = "http://127.0.0.1:8000"
EMULATOR = "http://127.0.0.1:8085/v1/projects/demo-readlayer/databases/(default)/documents"
PORT = 9444
PROFILE = Path(os.environ.get("M8_PROFILE", "/tmp/gloss-m8-profile"))  # never in the repo
CFT = sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/*.app/Contents/MacOS/*")))[-1]
FIX_DIR = Path(__file__).resolve().parent / "m8_fixtures"
FIX_PORT = 8765
FIX = "http://fixtures.gloss-test.example"
RULES = (f"MAP fixtures.gloss-test.example:80 127.0.0.1:{FIX_PORT}, "
         f"MAP netbanking.hdfcbank.com:80 127.0.0.1:{FIX_PORT}, MAP mail.google.com 127.0.0.1:{FIX_PORT}")
SITES = {
    "bbc": "https://www.bbc.co.uk/news/articles/cm78pwdp3n5qo",
    "guardian": "https://www.theguardian.com/business/2026/oct/12/ifs-budget-report-spending-pressures-tax-inflation-john-healey",
    "hindu": "https://www.thehindu.com/business/Economy/retail-inflation-rises-in-september-on-costlier-food-items/article71574789.ece",
}
CARD_JS = """(() => { const c = document.querySelector('.rl-card'); if (!c || c.hidden) return null;
  const ex = c.querySelector('.rl-card__explain'), says = c.querySelector('.rl-card__says');
  return {state: ex ? ex.dataset.state : null, says: says && !says.hidden ? says.textContent.trim().slice(0, 140) : null}; })()"""
COUNTS_JS = """({marks: document.querySelectorAll('.rl-mark').length, markers: document.querySelectorAll('.rl-pmark').length,
  paragraphs: document.querySelectorAll('[data-rl-paragraph]').length, preread: !!document.querySelector('.rl-preread'),
  toast: document.querySelector('.rl-ext-toast')?.textContent || null})"""
TRACE_JS = "!!document.querySelector('[data-rl-mounted],[data-rl-paragraph],[data-rl-ui],.rl-mark')"
# Our CSS on the page? insertCSS sheets aren't in document.styleSheets, so probe a styled class.
CSS_JS = """(() => { const d = document.createElement('div'); d.className = 'rl-ext-toast'; document.body.append(d);
  const fixed = getComputedStyle(d).position === 'fixed'; d.remove(); return fixed; })()"""

results: dict[str, object] = {}


def record(key: str, value: object) -> None:
    results[key] = value
    print(f"[{key}]", json.dumps(value, default=str)[:600])


class Session(cdp.Page):
    """A CDP target with a background reader, so events (Network on the worker) are kept."""

    def __init__(self, ws):
        super().__init__(ws)
        self.pending: dict[int, asyncio.Future] = {}
        self.events: list[dict] = []
        self.bodies: dict[str, str] = {}  # url → response body, from Fetch interception
        self.task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
            elif "method" in msg:
                self.events.append(msg)
                if msg["method"] == "Fetch.requestPaused":
                    asyncio.get_running_loop().create_task(self._keep_body(msg["params"]))

    async def _keep_body(self, params):
        """A paused response (POST /v1/content): keep its body, then let it through unchanged."""
        try:
            got = await self.send("Fetch.getResponseBody", requestId=params["requestId"])
            body = got.get("body", "")
            if got.get("base64Encoded"):
                import base64
                body = base64.b64decode(body).decode()
            self.bodies[params["request"]["url"]] = body
        finally:
            await self.send("Fetch.continueResponse", requestId=params["requestId"])

    async def goto(self, url, wait=1.0):
        # The first navigation of a fresh Chrome for Testing profile sometimes never confirms
        # (seen once in three launches); the page still loads, so don't fail the run on it.
        try:
            await self.send("Page.navigate", timeout=30, url=url)
        except TimeoutError:
            print(f"   (navigate to {url} not confirmed in 30 s; continuing)", flush=True)
        await asyncio.sleep(wait)

    async def send(self, method, timeout=120, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        msg = await asyncio.wait_for(fut, timeout)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})


async def attach(ws_url: str) -> Session:
    return Session(await websockets.connect(ws_url, max_size=50_000_000))


def targets() -> list[dict]:
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())


def serve_fixtures() -> None:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(FIX_DIR))
    handler.log_message = lambda *a: None  # type: ignore[method-assign]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", FIX_PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def launch(scale: int = 1) -> None:
    """`scale` 2 forces device scale 2, so the popup (which takes no metrics override) is captured
    at 2x too (decision 61 landing stills)."""
    subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"], check=False)
    shutil.rmtree(PROFILE, ignore_errors=True)
    extra = [f"--force-device-scale-factor={scale}"] if scale != 1 else []
    subprocess.Popen([CFT, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                      "--no-first-run", "--window-size=1440,900", *extra, "--enable-unsafe-extension-debugging",
                      f"--load-extension={EXT_DIR}", f"--disable-extensions-except={EXT_DIR}",
                      f"--host-resolver-rules={RULES}", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
            return
        except OSError:
            time.sleep(0.25)
    raise SystemExit("chrome for testing did not start")


def spend() -> float:
    day = datetime.now(UTC).date().isoformat()
    # "Bearer owner": the emulator's admin bypass of the deny-all rules (local only).
    req = urllib.request.Request(f"{EMULATOR}/ops/spend/days/{day}", headers={"Authorization": "Bearer owner"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            fields = json.load(r).get("fields", {})
    except urllib.error.HTTPError:
        return 0.0
    v = fields.get("cost_usd", {})
    return float(v.get("doubleValue", v.get("integerValue", 0)))


class Harness:
    def __init__(self, browser: Session, page: Session, page_id: str, worker: Session):
        self.browser, self.p, self.page_id, self.sw = browser, page, page_id, worker

    def content_id(self, since: int = 0) -> str | None:
        import re
        for r in self.api_requests(since):
            m = re.search(r"/v1/content/([0-9a-f]{32})", r["request"]["url"])
            if m:
                return m.group(1)
        return None

    def api_requests(self, since: int = 0) -> list[dict]:
        return [e["params"] for e in self.sw.events[since:]
                if e["method"] == "Network.requestWillBeSent" and e["params"]["request"]["url"].startswith(API)]

    async def tab_id(self) -> str:
        # The tab holding our page, matched on the browser's own URLs (an error page's
        # location.href is chrome-error://…, while the tab keeps the URL it tried).
        infos = (await self.browser.send("Target.getTargets", filter=[{}]))["targetInfos"]
        url = next(t["url"] for t in infos if t["targetId"] == self.page_id)
        tabs = [t for t in infos if t["type"] == "tab" and t["url"] == url]
        return tabs[0]["targetId"]

    async def popup(self) -> Session:
        before = {t["id"] for t in targets()}
        await self.browser.send("Extensions.triggerAction", id=EXT_ID, targetId=await self.tab_id())
        for _ in range(40):
            new = [t for t in targets() if t["id"] not in before and t["url"].endswith("/popup.html")]
            if new:
                pop = await attach(new[0]["webSocketDebuggerUrl"])
                await pop.send("Runtime.enable")
                await pop.send("Page.enable")
                for _ in range(40):
                    if await pop.eval("document.getElementById('who')?.textContent !== '…'"):
                        return pop
                    await asyncio.sleep(0.25)
                return pop
            await asyncio.sleep(0.25)
        raise RuntimeError("popup did not open")

    async def close(self, s: Session) -> None:
        tid = next((t["id"] for t in targets() if t["url"].endswith("/popup.html")), None)
        await s.ws.close()
        if tid:
            await self.browser.send("Target.closeTarget", targetId=tid)

    async def press_read(self, shot: str | None = None) -> str:
        pop = await self.popup()
        await pop.eval("document.getElementById('read').click(); 1")
        message = ""
        for _ in range(80):
            message = await pop.eval("document.getElementById('message').textContent")
            if message and message != "Reading this page…":
                break
            await asyncio.sleep(0.25)
        if shot:
            print(f"[{shot}]", await pop.shot(shot))
        await self.close(pop)
        return message

    async def goto(self, url: str, wait: float = 4.0) -> None:
        await self.p.goto(url, wait=wait)

    async def wait_notes(self, timeout: float = 240) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            toast = await self.p.eval("document.querySelector('.rl-ext-toast')?.textContent || ''")
            if "Notes are ready" in toast or "Nothing new" in toast:
                return True
            if toast and not toast.endswith("Reading this page…") and "Gloss" in toast and "ready" not in toast:
                print("[toast]", toast)
                return False
            await asyncio.sleep(1)
        return False

    async def open_card(self) -> dict | None:
        await self.p.eval("(() => { const m = document.querySelector('.rl-mark:not(.rl-mark--ask)'); "
                          "m.scrollIntoView({block: 'center'}); m.click(); return 1; })()")
        for _ in range(120):
            card = await self.p.eval(CARD_JS)
            if card and card["state"] == "ready":
                return card
            await asyncio.sleep(0.5)
        return await self.p.eval(CARD_JS)

    async def read_site(self, reader: str, name: str, url: str, negative: bool = False) -> dict:
        step(f"read {reader} {name}")
        await self.p.viewport(1440)
        await self.goto(url, wait=6)
        out: dict[str, object] = {}
        if negative:
            # Before any click: no activeTab, so the worker can't inject; nothing on the page; no API call.
            mark = len(self.sw.events)
            out["executeScript_before_click"] = await self.sw.eval(
                # No "tabs" permission: the worker can't see URLs, so take the active tab.
                "chrome.tabs.query({active: true, lastFocusedWindow: true}).then(([t]) => "
                "chrome.scripting.executeScript({target: {tabId: t.id}, func: () => 1}))"
                ".then(() => 'ran', e => 'refused: ' + e.message)")
            await asyncio.sleep(1)
            out["page_traces_before_click"] = await self.p.eval(TRACE_JS)
            out["api_calls_before_click"] = len(self.api_requests(mark))
        out["popup"] = await self.press_read(f"popup-{reader}-{name}")
        out["notes"] = await self.wait_notes()
        out["counts"] = await self.p.eval(COUNTS_JS)
        if out["counts"]["marks"]:  # type: ignore[index]
            out["card"] = await self.open_card()
        out["shot"] = await self.p.shot(f"overlay-{reader}-{name}-1440-light")
        return out


def step(text: str) -> None:
    print(f"-- {time.strftime('%H:%M:%S')} {text}", flush=True)


async def demo_sign_in(h: Harness, persona: str | None = None) -> None:
    step("demo sign-in")
    await h.p.reset_auth(W)
    await h.goto(W + "/" + (f"?persona={persona}" if persona else ""), wait=3)
    await h.p.wait_for(".lp-nav__cta", 20)
    await h.p.eval("document.querySelector('.lp-nav__cta').click(); 1")
    await asyncio.sleep(4)
    step(f"signed in as demo: {await h.p.eval('location.href')}")


async def connect(h: Harness, query: str = "", shots: str | None = None) -> str:
    step("connect page")
    await h.goto(W + "/connect" + query, wait=3)
    await h.p.wait_for(".connect__state", 20)
    for _ in range(20):
        state = await h.p.eval("document.querySelector('.connect__state').textContent")
        if not state.startswith("Looking"):
            break
        await asyncio.sleep(0.25)
    if shots:
        await connect_shots(h, shots)
    await h.p.click_text(".connect__panel button", "Connect", 2)
    return await h.p.eval("document.querySelector('.connect__state').textContent")


async def connect_shots(h: Harness, name: str) -> None:
    for w, dark in ((1440, False), (1440, True), (390, False)):
        await h.p.viewport(w, dark=dark)
        await h.p.eval(f"document.documentElement.dataset.theme = '{'dark' if dark else 'light'}'; 1")
        await asyncio.sleep(0.6)
        a = await h.p.audit()
        tag = f"{w}-{'dark' if dark else 'light'}"
        print(f"[connect {name} {tag}] axe={a['axe']} hscroll={a['hscroll']} small={json.dumps(a['small'])[:160]}",
              await h.p.shot(f"connect-{name}-{tag}", full=True))
        results[f"connect_axe_{name}_{tag}"] = a["axe"]
    await h.p.viewport(1440)
    await h.p.eval("document.documentElement.dataset.theme = 'light'; 1")


async def popup_shots(h: Harness) -> None:
    for dark in (False, True):
        pop = await h.popup()
        # A popup can't take a metrics override; only the colour scheme is emulated.
        await pop.send("Emulation.setEmulatedMedia",
                       features=[{"name": "prefers-color-scheme", "value": "dark" if dark else "light"}])
        await asyncio.sleep(0.4)
        a = await pop.audit()
        tag = "dark" if dark else "light"
        print(f"[popup {tag}] axe={a['axe']} small={json.dumps(a['small'])[:160]}", await pop.shot(f"popup-{tag}"))
        results[f"popup_axe_{tag}"] = a["axe"]
        await h.close(pop)


async def refusals(h: Harness) -> None:
    step("refusals")
    cases = {"password page": f"{FIX}/login.html", "bank login": "http://netbanking.hdfcbank.com/bank.html",
             "gmail tab": "https://mail.google.com/mail/u/0/"}
    for name, url in cases.items():
        await h.goto(url, wait=3)
        mark = len(h.sw.events)
        message = await h.press_read(f"popup-refused-{name.replace(' ', '-')}")
        page_ok = await h.p.eval("location.protocol.startsWith('http')")  # error pages can't be probed
        record(f"refused {name}", {
            "popup": message,
            "page_traces": await h.p.eval(TRACE_JS) if page_ok else "n/a (error page)",
            "our_css_on_page": await h.p.eval(CSS_JS) if page_ok else "n/a (error page)",
            "api_calls": len(h.api_requests(mark)),
        })


async def redaction(h: Harness) -> str | None:
    step("redaction page")
    # Pause POST /v1/content at the response so its body can be read (the worker's own fetch).
    await h.sw.send("Fetch.enable", patterns=[{"urlPattern": f"{API}/v1/content", "requestStage": "Response"}])
    await h.goto(f"{FIX}/pii-news.html", wait=3)
    mark = len(h.sw.events)
    message = await h.press_read()
    await h.wait_notes()
    sent = [r for r in h.api_requests(mark) if r["request"]["method"] == "POST" and r["request"]["url"].endswith("/v1/content")]
    body = json.loads(sent[0]["request"].get("postData", "{}")) if sent else {}
    text = json.dumps(body)
    response = json.loads(h.sw.bodies.get(f"{API}/v1/content", "{}") or "{}")
    record("redaction", {
        "popup": message,
        "request_has_email_placeholder": "[REDACTED:email]" in text,
        "request_has_phone_placeholder": "[REDACTED:phone]" in text,
        "raw_email_sent": "markets.desk@fixture-times.in" in text,
        "raw_phone_sent": "98201 44312" in text,
        "pii_found_before_backstop": response.get("pii_found_before_backstop"),
        "status": response.get("status"),
    })
    await h.sw.send("Fetch.disable")
    return response.get("content_id")


async def finish_onboarding(h: Harness) -> None:
    await h.p.wait_for("#welcome-title", 30)
    await tick(h.p, "Software")
    await tick(h.p, "Economics")
    await type_text(h.p, ".freetext__input", "inflation, interest rates")
    await h.p.eval("document.querySelector('.consent__check input').click(); 1")
    await h.p.click_text("button", "Continue", 1)
    await h.p.wait_for(".matches", 60)
    await h.p.click_text("button", "Continue", 1)
    await h.p.wait_for(".discover-card:not(.discover-card--ghost)", 90)
    await asyncio.sleep(1)
    await h.p.click_text("button", "Start exploring", 4)


async def main() -> None:
    serve_fixtures()
    launch()
    start_spend = spend()
    version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version").read())
    browser = await attach(version["webSocketDebuggerUrl"])
    # A tab of our own (the start-up tab is sometimes replaced while Chrome settles).
    created = (await browser.send("Target.createTarget", url="about:blank"))["targetId"]
    await asyncio.sleep(1)
    first = next(t for t in targets() if t["id"] == created)
    page = await attach(first["webSocketDebuggerUrl"])
    await page.send("Page.enable")
    await page.send("Runtime.enable")
    for _ in range(40):
        sw = next((t for t in targets() if t["url"].startswith(f"chrome-extension://{EXT_ID}/")
                   and t["type"] == "service_worker"), None)
        if sw:
            break
        await asyncio.sleep(0.25)
    worker = await attach(sw["webSocketDebuggerUrl"])
    await worker.send("Runtime.enable")
    await worker.send("Network.enable")
    h = Harness(browser, page, created, worker)
    record("browser", version["Browser"])
    try:
        # --- demo reader: connect from the web app, then the three sites
        await demo_sign_in(h)
        record("demo connect", await connect(h, shots="demo"))
        await popup_shots(h)
        ext_ids: dict[str, str] = {}
        for i, (name, url) in enumerate(SITES.items()):
            mark = len(worker.events)
            got = await h.read_site("demo", name, url, negative=(i == 0))
            ext_ids[name] = h.content_id(mark) or ""
            got["content_id"] = ext_ids[name]
            record(f"demo {name}", got)
        # Design: each size or scheme is set before the page loads, then read (the doc is reused).
        step("design pass")
        for name, url, w, dark in (("bbc", SITES["bbc"], 390, False), ("bbc", SITES["bbc"], 1440, True),
                                   ("dark-page", f"{FIX}/dark-news.html", 1440, False)):
            await h.p.viewport(w, dark=dark)
            await h.goto(url, wait=5)
            await h.press_read()
            await h.wait_notes()
            scheme = await h.p.eval("document.documentElement.getAttribute('data-rl-scheme')")
            if await h.p.eval("document.querySelectorAll('.rl-mark').length"):
                await h.open_card()
            tag = f"{w}-{'dark-os' if dark else 'light-os'}"
            record(f"design {name} {tag}", {"scheme": scheme, "shot": await h.p.shot(f"overlay-demo-{name}-{tag}")})
        await h.p.viewport(1440)

        await refusals(h)
        pii_id = await redaction(h)
        record("redaction content id", pii_id)

        # --- visibility: a second demo reader doesn't see the first one's extension pages
        await demo_sign_in(h)
        other = {}
        for name, cid in ext_ids.items():
            other[name] = (await h.p.api(API, "GET", f"/v1/content/{cid}"))["status"]
        library = (await h.p.api(API, "GET", "/v1/content?density=balanced"))["body"] or []
        record("second reader", {"detail_status": other,
                                 "in_library": [n for n, c in ext_ids.items() if c in {r["id"] for r in library}]})

        # --- Google reader: /connect → /welcome → finish → back on /connect → connect → read
        await h.p.reset_auth(W)
        await h.goto(W + "/", wait=3)
        email = f"m8-{int(time.time())}@example.com"
        await h.p.eval(f"window.__rlEmulatorSignIn({json.dumps(email)}, 'M8 Check')")
        await asyncio.sleep(4)
        # Popup backstop first: this unfinished reader's session handed straight to the extension.
        token = await h.p.token()
        await worker.eval(f"chrome.storage.session.set({{session: {{idToken: {json.dumps(token)}, refreshToken: 'x', "
                          f"expiresAt: Date.now() + 3e6, apiKey: 'demo-key', persona: null, density: 'balanced'}}}}).then(() => 1)")
        await h.goto(SITES["bbc"], wait=5)
        pop = await h.popup()
        record("unfinished popup", {"setup_shown": await pop.eval("!document.getElementById('setup').hidden"),
                                    "read_hidden": await pop.eval("document.getElementById('connected').hidden")})
        print("[popup setup]", await pop.shot("popup-setup"))
        await h.close(pop)
        record("unfinished page traces", await h.p.eval(TRACE_JS))
        await worker.eval("chrome.storage.session.clear().then(() => 1)")
        await h.goto(W + "/connect", wait=4)
        record("connect redirects to", await h.p.eval("location.pathname"))
        await finish_onboarding(h)
        for _ in range(40):
            if await h.p.eval("location.pathname") == "/connect":
                break
            await asyncio.sleep(0.5)
        record("after onboarding", await h.p.eval("location.pathname"))
        record("google connect", await connect(h, shots="google"))
        for name, url in SITES.items():
            record(f"google {name}", await h.read_site("google", name, url))
        await h.goto(W + "/", wait=3)  # the session lives in the web app's storage
        library = (await h.p.api(API, "GET", "/v1/content?density=balanced"))["body"] or []
        record("google library has its pages", [n for n, c in ext_ids.items() if c in {r["id"] for r in library}])
    finally:
        record("spend_usd", round(spend() - start_spend, 4))
        out = Path(os.environ.get("SHOTS_OUT", "/tmp/gloss-shots")) / "m8-results.json"
        out.write_text(json.dumps(results, indent=2, default=str))
        print("[results]", out)
        subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"], check=False)


if __name__ == "__main__":
    asyncio.run(main())
