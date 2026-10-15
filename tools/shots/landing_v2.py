"""Decision 63 checks (docs/plans/landing-v2.md, acceptance 2): local previews only, no network
beyond the pages' own assets. `/` before (a `main` build) and after (this branch) must give the
same first view at 1440 and 390; `/v2` at 1440 and 390, light and dark: axe serious/critical 0, no
horizontal scroll; the demo reshapes and marks a clause. Shots into docs/evidence/landing-v2/.

    BEFORE=<dist dir of main> AFTER=<dist dir of this branch> \
      uv run --project apps/api python tools/shots/landing_v2.py
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "evidence" / "landing-v2"
PORTS = {"before": 4181, "after": 4182}


def serve(dist: str, port: int) -> subprocess.Popen:
    return subprocess.Popen(
        ["pnpm", "--filter", "web", "exec", "vite", "preview", "--outDir", dist, "--port", str(port), "--strictPort"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


async def view(p: cdp.Page, url: str, width: int, dark: bool = False, wait: float = 3.5) -> None:
    await p.send("Emulation.setDeviceMetricsOverride", width=width, height=900 if width > 600 else 844,
                 deviceScaleFactor=1, mobile=width < 640)
    await p.send("Emulation.setEmulatedMedia", features=[
        {"name": "prefers-color-scheme", "value": "dark" if dark else "light"},
        {"name": "prefers-reduced-motion", "value": "reduce"}])
    await p.goto(url, wait=wait)


async def shot_bytes(p: cdp.Page) -> bytes:
    import base64
    r = await p.send("Page.captureScreenshot", format="png")
    return base64.b64decode(r["data"])


async def main() -> None:
    before, after = os.environ["BEFORE"], os.environ["AFTER"]
    OUT.mkdir(parents=True, exist_ok=True)
    servers = [serve(before, PORTS["before"]), serve(after, PORTS["after"])]
    time.sleep(4)
    report: dict = {}
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        # / before and after: the same first view.
        for width in (1440, 390):
            shots = {}
            for name, port in PORTS.items():
                await view(p, f"http://localhost:{port}/", width)
                await p.eval("localStorage.clear(); 1")
                await view(p, f"http://localhost:{port}/", width)
                shots[name] = await shot_bytes(p)
                (OUT / f"root-{name}-{width}.png").write_bytes(shots[name])
            same = hashlib.sha256(shots["before"]).hexdigest() == hashlib.sha256(shots["after"]).hexdigest()
            report[f"/ first view identical at {width}"] = same
        # /v2: audits at each width and theme.
        base = f"http://localhost:{PORTS['after']}/v2"
        for width in (1440, 390):
            for dark in (False, True):
                await view(p, base, width, dark)
                await p.eval("window.scrollTo(0, document.body.scrollHeight); 1")
                await asyncio.sleep(1.5)
                await p.eval("window.scrollTo(0, 0); 1")
                key = f"/v2 {width} {'dark' if dark else 'light'}"
                report[key] = await p.audit()
                report[key]["robots"] = await p.eval("document.querySelector('meta[name=robots]')?.content || null")
                (OUT / f"v2-{width}-{'dark' if dark else 'light'}.png").write_bytes(await shot_bytes(p))
        # The demo: Full → 2 min, then focus the second line; its clause is marked.
        await view(p, base, 1440)
        await p.eval("""(() => { [...document.querySelectorAll('.lp2-controls button')]
          .find(b => b.textContent === '2 min').click(); return 1; })()""")
        await asyncio.sleep(0.6)
        await p.eval("document.querySelectorAll('.lp2-line')[1].focus(); 1")
        await asyncio.sleep(0.3)
        report["demo after 2 min + focus"] = await p.eval("""({lines: [...document.querySelectorAll('.lp2-line__text')].map(e => e.textContent),
          marked: [...document.querySelectorAll('.lp2-clause--on')].map(e => e.dataset.clause)})""")
        rect = await p.eval("""(() => { const r = document.querySelector('.lp2-demo').getBoundingClientRect();
          return {x: r.left, y: r.top + scrollY, w: r.width, h: r.height}; })()""")
        import base64
        r = await p.send("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                         clip={"x": rect["x"], "y": rect["y"], "width": rect["w"], "height": rect["h"], "scale": 1})
        (OUT / "v2-demo-2min-focus.png").write_bytes(base64.b64decode(r["data"]))
    finally:
        await ws.close()
        cdp.stop()
        for s in servers:
            s.terminate()
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
