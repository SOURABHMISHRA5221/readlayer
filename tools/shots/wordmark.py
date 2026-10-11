"""Render the README wordmark (Margo + "gloss") to docs/images/wordmark-{light,dark}.png."""

import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MARGO = """<svg width="64" height="64" viewBox="0 0 64 64"><path fill="ACCENT" opacity=".85" d="M8 55.5 q24 -5 48 0 v4 q-24 -4.5 -48 0z"/>
<path fill="PAPER" stroke="INK" stroke-width="3" stroke-linejoin="round" d="M17 8 h22 l11 11 v29 a6 6 0 0 1 -6 6 h-27 a6 6 0 0 1 -6 -6 v-34 a6 6 0 0 1 6 -6z"/>
<path fill="none" stroke="INK" stroke-width="3" stroke-linejoin="round" d="M39 8 v7 a4 4 0 0 0 4 4 h7"/>
<circle fill="INK" cx="25" cy="33" r="3.2"/><circle fill="INK" cx="39" cy="33" r="3.2"/>
<path fill="none" stroke="INK" stroke-width="2.6" stroke-linecap="round" d="M28.5 40.5 q3.5 3 7 0"/></svg>"""


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        for name, paper, ink, accent in (("light", "#ffffff", "#1c1c1c", "#0d6b62"), ("dark", "#121212", "#ececec", "#4fbfae")):
            svg = MARGO.replace("PAPER", paper).replace("INK", ink).replace("ACCENT", accent)
            html = (f"<html><head><link rel=stylesheet href='https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@800&display=swap'>"
                    f"<style>html,body{{margin:0;background:transparent}}div{{display:inline-flex;align-items:center;gap:14px;padding:8px;"
                    f"font:800 64px/1 'Schibsted Grotesk';letter-spacing:-.04em;color:{ink}}}</style></head><body><div id=w>{svg}gloss</div></body></html>")
            await p.viewport(600, 120)
            await p.send("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            await p.goto("data:text/html;base64," + base64.b64encode(html.encode()).decode(), wait=3)
            await p.eval("document.fonts.ready.then(() => 1)")
            box = await p.eval("(() => { const r = document.getElementById('w').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
            r = await p.send("Page.captureScreenshot", format="png", clip={"x": box[0], "y": box[1], "width": box[2], "height": box[3], "scale": 2})
            out = ROOT / f"docs/images/wordmark-{name}.png"
            out.write_bytes(base64.b64decode(r["data"]))
            print(out, out.stat().st_size)
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
