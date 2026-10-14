"""Decision 62 live check (plan acceptance 3, R6): the production extension 0.8.2 against
https://glossreader.web.app as one demo reader. Landing axe at 1440 and 390; demo sign-in and
Connect on the new address; on the Fireship YouTube video (stored in production, so `open_media`
returns early: no lookup, no transcript, no model call), Open in Gloss opens the reader on the new
address with the transcript and its marks. No note is opened. The reader is deleted with DELETE
/v1/me and confirmed gone (read only).

    make extension-zip   # the production build in apps/extension/dist
    uv run --project apps/api python tools/shots/gloss_live.py --confirmed
    uv run --project apps/api python tools/shots/gloss_live.py --axe-only   # no sign-in, no writes

The report is also written to docs/evidence/gloss-address/live[-axe].json.

Writes in production: 1 anonymous demo reader (`users/{uid}` with its `ingested` entry), deleted.
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import m8  # noqa: E402
import websockets  # noqa: E402
from landing_extension import open_harness  # noqa: E402
from live_site import WEB  # noqa: E402
from readiness_live import UID_JS, gone  # noqa: E402

API = "https://readlayer-api-d2sfihz3za-el.a.run.app"
VIDEO = "https://www.youtube.com/watch?v=wajoP_5Cpw8"
FIRESHIP = "93053af2e368625142213283d9abe557"
READER_JS = """({url: location.href, transcript: !!document.querySelector('.prose--transcript'),
  marks: document.querySelectorAll('.rl-mark').length,
  api: performance.getEntriesByType('resource').map(e => e.name).filter(n => n.startsWith(%s))
    .map(n => n.split('?')[0].replace(%s, ''))})""" % (json.dumps(API), json.dumps(API))


EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "gloss-address"


def built_for_production() -> None:
    js = "".join(p.read_text(errors="ignore") for p in m8.EXT_DIR.glob("*.js"))
    manifest = json.loads((m8.EXT_DIR / "manifest.json").read_text())
    if manifest["version"] != "0.8.2" or "glossreader.web.app" not in js or "127.0.0.1:8000" in js:
        raise SystemExit("apps/extension/dist is not the 0.8.2 production build: run `make extension-zip`")


async def landing_axe(h: m8.Harness, report: dict) -> None:
    for width in (1440, 390):
        await h.p.viewport(width)
        await h.goto(WEB + "/", wait=4)
        await h.p.eval("window.scrollTo(0, document.body.scrollHeight); 1")
        await asyncio.sleep(2)
        report[f"landing axe {width}"] = await h.p.audit()
        report[f"landing h-scroll {width}"] = await h.p.eval(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth")
    await h.p.viewport(1440)


async def open_in_gloss(h: m8.Harness, report: dict) -> None:
    await h.goto(VIDEO, wait=6)
    pop = await h.popup()
    report["popup"] = await pop.eval("""({video: !document.getElementById('video-actions').hidden,
      who: document.getElementById('who').textContent})""")
    if not report["popup"]["video"]:
        raise SystemExit("the popup did not offer Open in Gloss on the video")
    await pop.eval("document.getElementById('open-video').click(); 1")
    try:
        for _ in range(40):
            message = await pop.eval("document.getElementById('message').textContent")
            if message and message != "Opening this video in Gloss…":
                report["popup message"] = message
                break
            await asyncio.sleep(0.25)
    except websockets.exceptions.ConnectionClosed:
        report["popup message"] = "(popup closed: the new tab took focus)"
    tab = None
    for _ in range(60):
        tab = next((t for t in m8.targets() if t["type"] == "page" and t["url"].startswith(f"{WEB}/read/")), None)
        if tab:
            break
        await asyncio.sleep(0.5)
    if tab is None:
        raise SystemExit(f"no reader tab opened ({report.get('popup message')})")
    reader = await m8.attach(tab["webSocketDebuggerUrl"])
    await reader.send("Runtime.enable")
    end, state = time.time() + 90, {}
    while time.time() < end:
        state = await reader.eval(READER_JS)
        if state["transcript"] and state["marks"]:
            break
        await asyncio.sleep(1)
    report["reader"] = {**state, "api": sorted(set(state.get("api", [])))}
    await reader.ws.close()
    if not state.get("url", "").startswith(f"{WEB}/read/{FIRESHIP}"):
        raise SystemExit(f"reader opened at {state.get('url')}")


async def axe_only() -> None:
    m8.W, m8.API, m8.RULES = WEB, API, "MAP nothing.invalid 127.0.0.1"
    report: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    m8.launch()
    try:
        await landing_axe(await open_harness(), report)
    finally:
        subprocess.run(["pkill", "-f", f"remote-debugging-port={m8.PORT}"], check=False)
        save(report, "live-axe.json")


def save(report: dict, name: str) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))


async def main() -> None:
    if "--axe-only" in sys.argv:
        return await axe_only()
    if "--confirmed" not in sys.argv:
        raise SystemExit("Build with `make extension-zip`, then pass --confirmed.")
    built_for_production()
    m8.W, m8.API, m8.RULES = WEB, API, "MAP nothing.invalid 127.0.0.1"
    report: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    uid = None
    m8.launch()
    try:
        h = await open_harness()
        await landing_axe(h, report)
        await m8.demo_sign_in(h)
        uid = await h.p.eval(UID_JS % json.dumps(await h.p.token()))
        report["uid"] = uid
        report["connect"] = await m8.connect(h)
        try:
            await open_in_gloss(h, report)
        except SystemExit as e:
            report["open in gloss"] = f"FAILED: {e}"
    finally:
        try:
            if uid:
                await h.goto(WEB + "/", wait=4)
                report["cleanup"] = (await h.p.api(API, "DELETE", "/v1/me"))["status"]
        finally:
            subprocess.run(["pkill", "-f", f"remote-debugging-port={m8.PORT}"], check=False)
            if uid:
                await asyncio.sleep(3)
                report["deleted"] = gone(uid)
            report["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            save(report, "live.json")


if __name__ == "__main__":
    asyncio.run(main())
