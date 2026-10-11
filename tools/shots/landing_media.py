"""Landing media from the live reader (decision 44 V2 product shot, V4 clips).

    cd apps/api && uv run python -m scripts.landing_media_precheck      # read-only; run first
    uv run --project apps/api python tools/shots/landing_media.py --confirmed

As one temporary anonymous demo reader on the live site (deleted at the end with DELETE /v1/me,
which also deletes the Auth user): the phone product shot of the "bps" note on the
demo markets article, then four short clips. Writes AVIF/WebP images and WebM/MP4 clips with WebP
posters to apps/web/public/landing/. The precheck prints the exact production writes.
"""

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

WEB = "https://readlayer-sourabh-26.web.app"
API = "https://readlayer-api-751104670850.asia-south1.run.app"
CID = "2332418841faa08d5f5e157c2d038d1d"
OUT = Path(__file__).resolve().parents[2] / "apps/web/public/landing"
CLIP_W = 720  # decision 45 nit: sharp in the wider clip grid
CLIP_MAX_BYTES = 400_000
SHOT_PHONE_W = 300

READY = "!!document.querySelector('.rl-card:not([hidden]) .rl-card__explain[data-state=ready]')"


def js_rect(selector: str) -> str:
    return f"""(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();
      return {{x: r.left, y: r.top, w: r.width, h: r.height}}; }})()"""


def union(*rects, pad=32, vw=1440, vh=900):
    x0 = max(0, min(r["x"] for r in rects) - pad)
    y0 = max(0, min(r["y"] for r in rects) - pad)
    x1 = min(vw, max(r["x"] + r["w"] for r in rects) + pad)
    y1 = min(vh, max(r["y"] + r["h"] for r in rects) + pad)
    return {"x": int(x0), "y": int(y0), "w": int(x1 - x0) // 2 * 2, "h": int(y1 - y0) // 2 * 2}


async def click_mark(p, text):
    ok = await p.eval(f"""(() => {{ const m = [...document.querySelectorAll('.rl-mark[tabindex]')]
      .find(m => m.textContent.trim() === {json.dumps(text)}); if (!m) return false; m.click(); return true; }})()""")
    if not ok:
        raise SystemExit(f"no mark {text!r}")


async def center(p, selector):
    await p.eval(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block: 'center'}}); true")
    await asyncio.sleep(1.2)


async def wait_js(p, expr, timeout=20):
    for _ in range(int(timeout / 0.25)):
        if await p.eval(expr):
            return
        await asyncio.sleep(0.25)
    raise SystemExit(f"timed out waiting for {expr}")


async def open_reader(p, persona, wait_marks=True):
    await p.goto(f"{WEB}/read/{CID}?persona={persona}", wait=2)
    if wait_marks:
        await wait_js(p, "document.querySelectorAll('.rl-mark').length > 0", 40)


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def encode_image(png: Path, name: str, width: int):
    for scale, suffix in ((1, ""), (2, "@2x")):
        w = width * scale
        run("cwebp", "-quiet", "-q", "80", "-resize", str(w), "0", str(png), "-o", str(OUT / f"{name}{suffix}.webp"))
        run("ffmpeg", "-y", "-i", str(png), "-vf", f"scale={w}:-2,format=yuv420p", "-c:v", "libsvtav1",
            "-crf", "34", "-frames:v", "1", str(OUT / f"{name}{suffix}.avif"))


def encode_clip(segments, crop, name: str):
    """Frames (one or more recordings, hard cuts between them) → WebM, MP4 and a WebP poster."""
    tmp = Path(tempfile.mkdtemp(prefix="gloss-clip-"))
    # Frames arrive only when something changes; resample to a constant 24 fps (each output
    # frame is the latest captured one), so ffmpeg reads a plain image sequence.
    i, step = 0, 1 / 24
    for frames, ended in segments:
        k, t = 0, frames[0][0]
        while t < ended:
            while k + 1 < len(frames) and frames[k + 1][0] <= t:
                k += 1
            (tmp / f"{i:05}.jpg").write_bytes(frames[k][1])
            i, t = i + 1, t + step
    vf = f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},scale={CLIP_W}:-2,format=yuv420p"
    src = ["-framerate", "24", "-i", str(tmp / "%05d.jpg"), "-vf", vf, "-an"]
    for crf in (36, 40, 44, 48):
        run("ffmpeg", "-y", *src, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf), "-row-mt", "1",
            str(OUT / f"{name}.webm"))
        run("ffmpeg", "-y", *src, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf - 8),
            "-movflags", "+faststart", str(OUT / f"{name}.mp4"))
        sizes = [(OUT / f"{name}.{ext}").stat().st_size for ext in ("webm", "mp4")]
        if max(sizes) <= CLIP_MAX_BYTES:
            break
    else:
        raise SystemExit(f"{name}: still over {CLIP_MAX_BYTES} bytes: {sizes}")
    last = tmp / "poster.png"
    run("ffmpeg", "-y", "-sseof", "-0.1", "-i", str(OUT / f"{name}.mp4"), "-frames:v", "1", str(last))
    run("cwebp", "-quiet", "-q", "78", str(last), "-o", str(OUT / f"{name}-poster.webp"))
    shutil.rmtree(tmp)
    total = sum(len(f) for frames, _ in segments for _, f in frames)
    spans = [round(ended - frames[0][0], 2) for frames, ended in segments]
    return {"frames": i, "seconds": spans, "jpeg_bytes": total, "webm": sizes[0], "mp4": sizes[1]}


async def record(p, seconds_before, action, seconds_after):
    rec = cdp.Recorder()
    await rec.start()
    await asyncio.sleep(seconds_before)
    await action()
    await asyncio.sleep(seconds_after)
    frames = await rec.stop()
    return frames, rec.ended


async def product_shots(p, tmp: Path):
    # Decision 46 P3: only the phone shot is used (it sits on the hero card's corner).
    await p.send("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
    await open_reader(p, "newcomer")
    await center(p, '[data-rl-paragraph="p5"]')
    await click_mark(p, "bps")
    await wait_js(p, READY)
    await asyncio.sleep(0.8)
    r = await p.send("Page.captureScreenshot", format="png")
    phone = tmp / "phone.png"
    phone.write_bytes(cdp.base64.b64decode(r["data"]))
    encode_image(phone, "shot-phone", SHOT_PHONE_W)
    return {"phone": "shot-phone"}


async def clips(p, only=None):
    await p.viewport(1440)
    report = {}

    def want(name):
        return only is None or name in only

    async def nothing():
        return None

    # 1. Tap a highlight, the note slides in.
    if want("clip-note"):
        await clip_note(p, report)
    if want("clip-simpler"):
        await clip_simpler(p, report)
    if want("clip-know"):
        await clip_know(p, report, nothing)
    if want("clip-map"):
        await clip_map(p, report, nothing)
    return report


async def clip_note(p, report):
    await open_reader(p, "newcomer")
    await center(p, '[data-rl-paragraph="p5"]')
    para, rail = await p.eval(js_rect('[data-rl-paragraph="p5"]')), await p.eval(js_rect(".rail"))
    # The sidenote is up to 360px wide from the rail's left edge and may rise to the top bars.
    top = 120  # below the fixed bars
    right = min(1440, int(rail["x"]) + 380)
    crop = {"x": int(para["x"]) - 40, "y": top, "w": (right - int(para["x"]) + 40) // 2 * 2, "h": (900 - top) // 2 * 2}
    frames = await record(p, 0.8, lambda: click_mark(p, "tighter policy"), 3.2)
    report["clip-note"] = encode_clip([frames], crop, "clip-note")


async def clip_simpler(p, report):
    """"Say it simpler" (the cricket fan's "tighter policy" is one band above the lowest)."""
    await open_reader(p, "trader")
    await center(p, '[data-rl-paragraph="p5"]')
    await click_mark(p, "tighter policy")
    await wait_js(p, READY)
    await asyncio.sleep(0.5)
    crop = union(await p.eval(js_rect('[data-rl-paragraph="p5"]')), await p.eval(js_rect(".rl-card")), pad=40)

    async def simpler():
        await p.click_text(".rl-card button", "Say it simpler", 0.3)
        await wait_js(p, READY, 60)

    frames = await record(p, 0.8, simpler, 2.4)
    report["clip-simpler"] = encode_clip([frames], crop, "clip-simpler")


async def clip_know(p, report, nothing):
    """"Know this?" → "Not really": after a reload the term is a highlighted note."""
    await open_reader(p, "newcomer")
    await center(p, '[data-rl-paragraph="p16"]')
    crop = union(await p.eval(js_rect('[data-rl-paragraph="p16"]')), pad=40)
    a = await record(p, 0.8, lambda: p.click_text("button", "Not really", 0.2), 1.6)
    await open_reader(p, "newcomer")
    await center(p, '[data-rl-paragraph="p16"]')
    crop2 = union(await p.eval(js_rect('[data-rl-paragraph="p16"]')), pad=40)
    crop = {"x": min(crop["x"], crop2["x"]), "y": crop2["y"], "w": max(crop["w"], crop2["w"]), "h": max(crop["h"], crop2["h"])}
    b = await record(p, 0.2, nothing, 2.2)
    report["clip-know"] = encode_clip([a, b], crop, "clip-know")


async def clip_map(p, report, nothing):
    """The map gains nodes: the profile map, three ready-to-learn ideas marked known, the map again."""
    await p.goto(f"{WEB}/profile?persona=newcomer", wait=3)
    await wait_js(p, "!!document.querySelector('.kmap svg')", 60)
    await center(p, ".kmap")
    crop = union(await p.eval(js_rect(".kmap")), pad=16)
    a = await record(p, 0.2, nothing, 1.6)
    await open_reader(p, "newcomer")
    await center(p, '[data-rl-paragraph="p5"]')
    overview = (await p.api(API, "GET", "/v1/me/graph?view=overview&persona=newcomer"))["body"]
    rings = [n for n in overview["nodes"] if n["ready"]][:3]
    for n in rings:  # the "Know this? Yes" correction, as the reader would give it
        r = await p.api(API, "PATCH", f"/v1/me/graph/{n['id']}?persona=newcomer", {"state": "known"})
        report.setdefault("map_marked", []).append((n["label"], r["status"]))
    await p.goto(f"{WEB}/profile?persona=newcomer", wait=3)
    await wait_js(p, "!!document.querySelector('.kmap svg')", 60)
    await center(p, ".kmap")
    b = await record(p, 0.2, nothing, 2.4)
    report["clip-map"] = encode_clip([a, b], crop, "clip-map")


async def main():
    if "--confirmed" not in sys.argv:
        raise SystemExit("Run `uv run python -m scripts.landing_media_precheck` (in apps/api) first, then pass --confirmed.")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="gloss-media-"))
    cdp.launch()
    p, ws = await cdp.open_page()
    report = {}
    try:
        await p.viewport(1440)
        await cdp.Page.reset_auth(p, WEB)
        await p.goto(WEB + "/", wait=4)
        if not await p.click_text("button", "Newcomer", 5):
            raise SystemExit("no Newcomer button on the live front door")
        only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), None)
        if only is None or "product" in only:
            report["product"] = await product_shots(p, tmp)
        report["clips"] = await clips(p, only)
    finally:
        try:
            await p.send("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
            d = await p.api(API, "DELETE", "/v1/me")
            report["cleanup"] = d["status"]
        finally:
            print(json.dumps(report, indent=2))
            await ws.close()
            cdp.stop()
            shutil.rmtree(tmp, ignore_errors=True)


asyncio.run(main())
