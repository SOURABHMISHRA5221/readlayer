"""Landing refresh stills for "Gloss in your browser" (docs/plans/landing-refresh.md B, R7): the
production-built extension 0.8.1 on the live site as one demo reader, on Wikipedia's "Term structure
of interest rates" (it redirects to "Yield curve", a stored corpus doc, so the page is reused).

    cd apps/api && uv run python -m scripts.landing_media_precheck --refresh c_decompiler c_term_structure_of_interest_rates
    pnpm --filter extension build
    uv run --project apps/api python tools/shots/landing_extension.py --confirmed [--web-stills]

`--web-stills` also re-takes landing_media.py's shot-feed and shot-media as this same reader, so a
re-take costs no extra demo reader (the plan's count is two in all).

Kept from m8_live.py: load the built extension, demo sign-in, Connect, open the page, the popup
(shot before Read this page is pressed), Read this page, open one note, the window shot, DELETE
/v1/me. Encodes `shot-extension` (1440×900) and `shot-popup` (300 wide) at 1x and 2x into
apps/web/public/landing/ (Chrome runs at device scale 2: the popup takes no metrics override).

Writes in production: 1 anonymous demo reader with `users/{uid}` (its `ingested` entry for the
reused doc, events), deleted by DELETE /v1/me and confirmed gone (read only); explanation
generations only as the precheck lists (≤ 2); 0 `contents/`, `ext:`, `graph_growth/` docs and 0
ingest-counter increments (the page is reused and doesn't need growth).
"""

import asyncio
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import m8  # noqa: E402
from readiness_live import UID_JS, gone  # noqa: E402
from landing_media import shot_feed, shot_media  # noqa: E402
from stills import DPR, encode_still, png_size  # noqa: E402

from live_site import WEB as LIVE_WEB  # noqa: E402
LIVE_API = "https://readlayer-api-d2sfihz3za-el.a.run.app"
PAGE = "https://en.wikipedia.org/wiki/Term_structure_of_interest_rates"
YIELD_CURVE = "4a4a18915e77e0ae677f2f5c50e87b97"  # the stored doc m8_live's run reused
MARK = "term structure of interest rates"  # c_term_structure_of_interest_rates (precheck)
POPUP_W = 300


def built_for_production() -> None:
    js = "".join(p.read_text(errors="ignore") for p in m8.EXT_DIR.glob("*.js"))
    manifest = json.loads((m8.EXT_DIR / "manifest.json").read_text())
    if manifest["version"] != "0.8.1" or "readlayer-api" not in js or "127.0.0.1:8000" in js:
        raise SystemExit("apps/extension/dist is not the 0.8.1 production build: run `pnpm --filter extension build`")


async def open_harness() -> m8.Harness:
    version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{m8.PORT}/json/version").read())
    browser = await m8.attach(version["webSocketDebuggerUrl"])
    created = (await browser.send("Target.createTarget", url="about:blank"))["targetId"]
    await asyncio.sleep(1)
    page = await m8.attach(next(t for t in m8.targets() if t["id"] == created)["webSocketDebuggerUrl"])
    await page.send("Page.enable")
    await page.send("Runtime.enable")
    sw = None
    for _ in range(40):
        sw = next((t for t in m8.targets() if t["url"].startswith(f"chrome-extension://{m8.EXT_ID}/")
                   and t["type"] == "service_worker"), None)
        if sw:
            break
        await asyncio.sleep(0.25)
    if sw is None:
        raise SystemExit("the extension's service worker did not start")
    worker = await m8.attach(sw["webSocketDebuggerUrl"])
    await worker.send("Runtime.enable")
    await worker.send("Network.enable")
    return m8.Harness(browser, page, created, worker)


async def capture(session, path: Path) -> Path:
    r = await session.send("Page.captureScreenshot", format="png")
    path.write_bytes(m8.cdp.base64.b64decode(r["data"]))
    return path


async def shoot(h: m8.Harness, tmp: Path, report: dict) -> None:
    await h.p.send("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=DPR, mobile=False)
    await h.p.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
    mark = len(h.sw.events)
    await h.goto(PAGE, wait=6)

    pop = await h.popup()
    await pop.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
    await asyncio.sleep(0.6)
    popup_png = await capture(pop, tmp / "popup.png")
    report["popup px"] = png_size(popup_png)
    await pop.eval("document.getElementById('read').click(); 1")
    for _ in range(80):
        message = await pop.eval("document.getElementById('message').textContent")
        if message and message != "Reading this page…":
            break
        await asyncio.sleep(0.25)
    report["popup message"] = message
    await h.close(pop)

    report["notes"] = await h.wait_notes()
    report["content_id"] = h.content_id(mark)
    report["calls"] = sorted({f"{r['request']['method']} {r['request']['url'].split('?')[0].replace(m8.API, '')}"
                              for r in h.api_requests(mark)})
    if report["content_id"] != YIELD_CURVE:
        raise SystemExit(f"not the stored Yield curve doc: {report['content_id']}")
    if any(c.endswith(("/grow", "/analyse")) for c in report["calls"]):  # the precheck said neither
        raise SystemExit(f"growth or analysis called: {report['calls']}")
    found = await h.p.eval(f"""(() => {{ const m = [...document.querySelectorAll('.rl-mark')]
      .find(m => m.textContent.trim() === {json.dumps(MARK)}); if (!m) return false;
      m.scrollIntoView({{block: 'center'}}); m.click(); return true; }})()""")
    if not found:
        raise SystemExit(f"no mark {MARK!r}")
    for _ in range(120):
        card = await h.p.eval(m8.CARD_JS)
        if card and card["state"] == "ready":
            break
        await asyncio.sleep(0.5)
    report["card"] = card
    await asyncio.sleep(0.8)
    await capture(h.p, tmp / "window.png")  # encoded after cleanup (encode() below)


def encode(tmp: Path, report: dict) -> None:
    """After the reader is gone: each still on its own, so one over its size cap costs no other;
    the PNGs stay in `tmp` for a re-encode without a new capture."""
    for png, name, css_w in (("window.png", "shot-extension", 1440), ("popup.png", "shot-popup", POPUP_W)):
        if (tmp / png).exists():
            try:
                report[name] = encode_still(tmp / png, name, css_w)
            except SystemExit as e:
                report[name] = f"FAILED: {e}"


async def safely(report: dict, name: str, shot) -> None:
    try:
        await shot
    except SystemExit as e:
        report[name] = f"FAILED: {e}"


async def main() -> None:
    if "--confirmed" not in sys.argv:
        raise SystemExit("Run the --refresh precheck (apps/api) and `pnpm --filter extension build` first, then pass --confirmed.")
    built_for_production()
    m8.W, m8.API, m8.RULES = LIVE_WEB, LIVE_API, "MAP nothing.invalid 127.0.0.1"
    tmp = Path(tempfile.mkdtemp(prefix="gloss-ext-", dir=m8.cdp.OUT if m8.cdp.OUT.exists() else None))
    report: dict = {}
    uid = None
    m8.launch(scale=DPR)
    try:
        h = await open_harness()
        await m8.demo_sign_in(h)
        uid = await h.p.eval(UID_JS % json.dumps(await h.p.token()))
        report["uid"] = uid
        report["connect"] = await m8.connect(h)
        await safely(report, "extension", shoot(h, tmp, report))
        if "--web-stills" in sys.argv:  # re-takes of shot-feed / shot-media, same reader (R7 count)
            await safely(report, "shot-feed", shot_feed(h.p, tmp, report))
            await safely(report, "shot-media", shot_media(h.p, tmp, report))
    finally:
        try:
            if uid:
                await h.goto(LIVE_WEB + "/", wait=4)
                report["cleanup"] = (await h.p.api(LIVE_API, "DELETE", "/v1/me"))["status"]
        finally:
            import subprocess

            subprocess.run(["pkill", "-f", f"remote-debugging-port={m8.PORT}"], check=False)
            encode(tmp, report)
            report["pngs kept in"] = str(tmp)
            if uid:
                await asyncio.sleep(3)
                report["deleted"] = gone(uid)
            print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
