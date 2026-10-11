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
# Measured against the self-hosted files (decision 47), from the local preview (vite preview).
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4173"
PAGE = BASE + "/privacy"
CASES = [("Source Serif 4", "", "Georgia"), ("Source Serif 4", "italic ", "Georgia"),
         ("Schibsted Grotesk", "", "Arial")]


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.goto(PAGE, wait=4)
        await p.eval("document.fonts.ready.then(() => 1)")
        # Load every measured face explicitly: a page that hasn't used one yet would measure the
        # canvas default font instead.
        faces = [f"{style}400 100px '{web}'" for web, style, _ in CASES]
        loaded = await p.eval(f"Promise.all({json.dumps(faces)}.map(f => document.fonts.load(f))).then(r => r.map(x => x.length))")
        if not all(loaded):
            raise SystemExit(f"a web font didn't load: {loaded}")
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
