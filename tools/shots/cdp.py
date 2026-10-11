"""Headless Chrome over CDP for screenshots, axe and small UI checks (dev tooling, not shipped).

    uv run --project apps/api python tools/shots/<script>.py

Screenshots go to SHOTS_OUT (default /tmp/gloss-shots). Chrome runs with a throwaway profile in
SHOTS_PROFILE (default /tmp/gloss-shots-profile), never in the repo or a real browser profile.
"""

import asyncio
import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
OUT = Path(os.environ.get("SHOTS_OUT", "/tmp/gloss-shots"))
PROFILE = Path(os.environ.get("SHOTS_PROFILE", "/tmp/gloss-shots-profile"))  # never in the repo
AXE = next(Path(__file__).resolve().parents[2].glob("node_modules/.pnpm/axe-core@*/node_modules/axe-core/axe.min.js"))
AXE_JS = ("axe.run(document, {resultTypes: ['violations']}).then(r => r.violations"
          ".filter(v => ['serious','critical'].includes(v.impact)).map(v => v.id + ':' + v.nodes.length))")
SMALL_JS = """[...document.querySelectorAll('button, input, a[href], summary, [role=radio], [role=tab], select, textarea')]
  .filter(e => { const r = e.getBoundingClientRect(); if (!r.width || !r.height) return false;
    if (e.closest('p, li > a, .rl-card, .skip-link')) return false;
    return r.height < 44 || r.width < 44; })
  .map(e => (e.getAttribute('aria-label') || e.textContent.trim().slice(0, 24) || e.tagName) + ' ' +
    Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height))"""
TOKEN_JS = """(async () => { const db = await new Promise((res, rej) => { const r = indexedDB.open('firebaseLocalStorageDb'); r.onsuccess = () => res(r.result); r.onerror = rej; });
  const rows = await new Promise((res) => { const q = db.transaction('firebaseLocalStorage').objectStore('firebaseLocalStorage').getAll(); q.onsuccess = () => res(q.result); });
  const u = rows.map(r => r.value).find(v => v && v.stsTokenManager); return u ? u.stsTokenManager.accessToken : null; })()"""


class Page:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def send(self, method, **params):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:600])
        return r["result"].get("value")

    async def goto(self, url, wait=1.0):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(wait)

    async def wait_for(self, selector, timeout=20.0):
        end = time.time() + timeout
        while time.time() < end:
            if await self.eval(f"!!document.querySelector({json.dumps(selector)})"):
                return True
            await asyncio.sleep(0.25)
        return False

    async def shot(self, name, full=False):
        r = await self.send("Page.captureScreenshot", format="png", captureBeyondViewport=full)
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{name}.png"
        path.write_bytes(base64.b64decode(r["data"]))
        return str(path)

    async def viewport(self, width, height=900, dark=False, reduced=False):
        await self.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                        deviceScaleFactor=1, mobile=width < 640)
        feats = [{"name": "prefers-color-scheme", "value": "dark" if dark else "light"},
                 {"name": "prefers-reduced-motion", "value": "reduce" if reduced else "no-preference"}]
        await self.send("Emulation.setEmulatedMedia", features=feats)

    async def audit(self):
        await self.eval(AXE.read_text() + ";'axe'")
        return {"axe": await self.eval(AXE_JS),
                "hscroll": await self.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth"),
                "small": await self.eval(SMALL_JS)}

    async def click_text(self, selector, text, wait=0.5):
        ok = await self.eval(f"""(() => {{ const el = [...document.querySelectorAll({json.dumps(selector)})]
          .find(e => e.textContent.trim().includes({json.dumps(text)})); if (!el) return false; el.click(); return true; }})()""")
        await asyncio.sleep(wait)
        return ok

    async def token(self):
        return await self.eval(TOKEN_JS)

    async def api(self, base, method, path, body=None):
        tok = await self.token()
        js = f"""fetch({json.dumps(base + path)}, {{method: {json.dumps(method)}, headers: {{Authorization: 'Bearer ' + {json.dumps(tok)},
          'Content-Type': 'application/json'}}{', body: ' + json.dumps(json.dumps(body)) if body is not None else ''}}})
          .then(async r => ({{status: r.status, body: await r.json().catch(() => null)}}))"""
        return await self.eval(js)

    async def reset_auth(self, base):
        await self.goto(base + "/", wait=2)
        await self.eval("localStorage.clear(); sessionStorage.clear(); indexedDB.deleteDatabase('firebaseLocalStorageDb'); 'ok'")


def launch():
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={PROFILE}", "--no-first-run",
                      "--window-size=1440,900", "about:blank"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
            return
        except OSError:
            time.sleep(0.2)
    raise SystemExit("chrome did not start")


def stop():
    subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"], check=False)


async def open_page():
    targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())
    page = next(t for t in targets if t["type"] == "page")
    ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000)
    p = Page(ws)
    await p.send("Page.enable")
    await p.send("Runtime.enable")
    return p, ws
