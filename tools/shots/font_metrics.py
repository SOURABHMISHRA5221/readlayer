"""Fallback @font-face overrides for apps/web/src/styles/fonts.css, measured in Chrome.

size-adjust = width(web font) / width(local fallback) for the same sentence at 100px;
ascent/descent-override = the web font's ascent/descent at 100px divided by size-adjust.
"""

import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

SENTENCE = "The central bank kept the repo rate at 5.5%, as most economists had expected."
PAGE = ("data:text/html,<link rel=stylesheet href='https://fonts.googleapis.com/css2?family="
        "Schibsted+Grotesk:wght@400..800&family=Source+Serif+4:ital,opsz,wght@0,8..60,400..600;"
        "1,8..60,400..500&display=swap'><p style=\"font-family:'Source Serif 4'\">a</p>"
        "<p style=\"font-family:'Source Serif 4';font-style:italic\">a</p>"
        "<p style=\"font-family:'Schibsted Grotesk'\">a</p>")
CASES = [("Source Serif 4", "", "Georgia"), ("Source Serif 4", "italic ", "Georgia"),
         ("Schibsted Grotesk", "", "Arial")]


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.goto(PAGE, wait=4)
        await p.eval("document.fonts.ready.then(() => 1)")
        for web, style, local in CASES:
            m = await p.eval(f"""(() => {{ const c = document.createElement('canvas').getContext('2d');
              c.font = "{style}400 100px '{web}'"; const w = c.measureText({json.dumps(SENTENCE)});
              c.font = "{style}400 100px {local}"; const f = c.measureText({json.dumps(SENTENCE)});
              return {{w: w.width, f: f.width, a: w.fontBoundingBoxAscent, d: w.fontBoundingBoxDescent}}; }})()""")
            size = m["w"] / m["f"]
            print(f"{web} {style or 'upright'} vs {local}: size-adjust {size * 100:.1f}%, "
                  f"ascent-override {m['a'] / size:.1f}%, descent-override {m['d'] / size:.1f}%")
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
