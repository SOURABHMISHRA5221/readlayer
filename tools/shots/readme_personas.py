"""README "See it" pictures from the landing's demo card (no sign-in, no writes): the same Economic
Times paragraph read as each demo persona. demo.json is real pipeline output (verified notes,
docs/plans/landing-onboarding.md), so the pictures show what the product gives each reader.

    uv run --project apps/api python tools/shots/readme_personas.py

Writes three 2x PNG stills to a temp dir, then composes with ffmpeg into docs/images/:
personas.png (three panels side by side) and demo.gif (switching readers, ≤ 3 MB).
"""

import asyncio
import base64
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
from live_site import WEB  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "images"
PERSONAS = ["Software engineer", "Cricket fan", "Policy student"]
GIF_MAX = 3_000_000
RECT_JS = """(() => { const r = document.querySelector('.lp-demo').getBoundingClientRect();
  return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}; })()"""
CLICK_JS = """(() => { const b = [...document.querySelectorAll('.lp-demo [role=radio]')]
  .find(b => b.textContent.trim() === %s); if (!b) return false; b.click(); return true; })()"""


async def capture(tmp: Path) -> list[Path]:
    cdp.launch()
    p, ws = await cdp.open_page()
    shots = []
    try:
        await p.send("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=2, mobile=False)
        await p.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"},
                                                             {"name": "prefers-reduced-motion", "value": "reduce"}])
        await p.goto(WEB + "/", wait=4)
        if not await p.wait_for(".lp-demo [role=radio]", 20):
            raise SystemExit("no demo card on the landing")
        await p.eval("document.querySelector('.lp-demo').scrollIntoView({block: 'center'}); 1")
        for i, label in enumerate(PERSONAS):
            if not await p.eval(CLICK_JS % json.dumps(label)):
                raise SystemExit(f"no persona option {label!r}")
            await asyncio.sleep(2.5)  # the annotator re-inks and the note swaps
            rect = await p.eval(RECT_JS)
            r = await p.send("Page.captureScreenshot", format="png", captureBeyondViewport=False,
                             clip={"x": rect["x"], "y": rect["y"], "width": rect["w"], "height": rect["h"], "scale": 1})
            path = tmp / f"persona-{i}.png"
            path.write_bytes(base64.b64decode(r["data"]))
            shots.append(path)
            print(f"[{label}] {path} {rect['w']:.0f}x{rect['h']:.0f} css px")
    finally:
        await ws.close()
        cdp.stop()
    return shots


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def png_size(path: Path) -> tuple[int, int]:
    w, h = struct.unpack(">II", path.read_bytes()[16:24])
    return w, h


def compose(shots: list[Path], tmp: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Side by side, each panel scaled to 900 px wide (the 2x capture keeps text sharp), padded to the
    # tallest panel (the cards differ by a few px with their notes), 24 px gaps.
    panel_w = 900
    tallest = max(round(h * panel_w / w / 2) * 2 for w, h in map(png_size, shots))
    inputs = [a for s in shots for a in ("-i", str(s))]
    pads = ";".join(f"[{i}:v]scale={panel_w}:-2,pad={panel_w + (24 if i < 2 else 0)}:{tallest}:0:0:white[p{i}]"
                    for i in range(3))
    ffmpeg(*inputs, "-filter_complex", f"{pads};[p0][p1][p2]hstack=inputs=3", "-frames:v", "1", str(OUT / "personas.png"))
    # The GIF: each reader held 2.4 s with a 0.4 s cross-fade, 800 px wide, one shared palette.
    width = 800
    while True:
        gif_h = round(tallest * width / panel_w / 2) * 2 + 2  # ≥ every scaled frame
        clips = []
        for i, s in enumerate(shots):
            clip = tmp / f"hold-{i}.mp4"
            ffmpeg("-loop", "1", "-t", "2.8", "-i", str(s), "-vf", f"scale={width}:-2,pad={width}:{gif_h}:0:0:white,fps=12,format=yuv420p", str(clip))
            clips.append(clip)
        fade = (f"[0:v][1:v]xfade=transition=fade:duration=0.4:offset=2.4[a];"
                f"[a][2:v]xfade=transition=fade:duration=0.4:offset=4.8[b];"
                f"[b][0:v]xfade=transition=fade:duration=0.4:offset=7.2[v]")
        loop = tmp / "loop.mp4"
        ffmpeg(*[a for c in clips + [clips[0]] for a in ("-i", str(c))], "-filter_complex", fade, "-map", "[v]", str(loop))
        palette = tmp / "palette.png"
        ffmpeg("-i", str(loop), "-vf", "palettegen=max_colors=128:stats_mode=diff", str(palette))
        gif = OUT / "demo.gif"
        ffmpeg("-i", str(loop), "-i", str(palette), "-lavfi", "paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", str(gif))
        size = gif.stat().st_size
        print(f"[demo.gif] {width} px wide, {size:,} bytes")
        if size <= GIF_MAX or width <= 560:
            break
        width -= 80


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="readme-personas-"))
    try:
        shots = await capture(tmp)
        compose(shots, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
