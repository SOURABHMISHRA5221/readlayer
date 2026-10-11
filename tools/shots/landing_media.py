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
import statistics
import subprocess
import sys
import tempfile
import time
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

    # The four steps, in the landing's order (decision 46d).
    if want("clip-know"):
        await clip_know(p, report, nothing)
    if want("clip-note"):
        await clip_note(p, report)
    if want("clip-simpler"):
        await clip_simpler(p, report)
    if want("clip-map"):
        await clip_map(p, report, nothing)
    return report


# Decision 46d: every clip is a 16:10 tile at natural zoom. Recorded at deviceScaleFactor 2 in a
# 680px-wide viewport (body text 21px, column ≈ 600px, cards float under their term) and cropped
# to 660×412 CSS px around the whole text column, so lines are never cut; encoded at the crop's
# native 1320×824 (downscaled only if a clip can't meet the size budget, never upscaled). The
# margin's "N notes for you" list only exists ≥ 1200px, so clip 2's second take is recorded at
# 1280 and cropped to the rail, padded with the page colour to the same tile.
REC_W, REC_H, DPR = 680, 900, 2
WIDE_W = 1280
TILE_W, TILE_H = 660, 412  # CSS px, 16:10
CROPS_FILE = Path(__file__).resolve().parent / "clip_crops.json"


async def rec_view(p, width=REC_W):
    await p.send("Emulation.setDeviceMetricsOverride", width=width, height=REC_H, deviceScaleFactor=DPR, mobile=False)


def tile(x, y, width=REC_W, w=TILE_W, h=TILE_H):
    """A tile-sized crop (CSS px) at x, y, kept inside the viewport."""
    x = max(0, min(width - w, int(x)))
    y = max(0, min(REC_H - h, int(y)))
    return {"x": x, "y": y, "w": w, "h": h, "vw": width}


async def column_tile(p, y_top):
    """The tile centred on the article's text column, starting at y_top (CSS px)."""
    col = await p.eval(js_rect("[data-rl-paragraph]"))
    if col["w"] > TILE_W - 16:
        raise SystemExit(f"text column {col['w']:.0f}px doesn't fit a {TILE_W}px tile with padding")
    return tile(col["x"] + col["w"] / 2 - TILE_W / 2, y_top)


async def bring_to(p, selector, y=140):
    """Scroll so the element's top sits at y (CSS px) in the viewport."""
    await p.eval(f"""(() => {{ const e = document.querySelector({json.dumps(selector)});
      scrollBy(0, e.getBoundingClientRect().top - {y}); return true; }})()""")
    await asyncio.sleep(1.2)


async def paper_hex(p):
    rgb = await p.eval("getComputedStyle(document.body).backgroundColor")
    nums = [int(n) for n in rgb[rgb.index("(") + 1 : rgb.index(")")].split(",")[:3]]
    return "0x" + "".join(f"{n:02X}" for n in nums)


def encode_tiles(segments, name, poster_at=None, pad_color="0xFFFFFF"):
    """segments: [(frames, ended, crop)]; each crop in CSS px of its own viewport. Every segment is
    cropped at native resolution, padded (never scaled up) to the 1320×824 tile, then all are
    encoded as one clip. poster_at: seconds into the clip for the poster (default: last frame)."""
    tmp = Path(tempfile.mkdtemp(prefix="gloss-clip-"))
    out_dir = tmp / "out"
    out_dir.mkdir()
    tw, th = TILE_W * DPR, TILE_H * DPR - 1  # 1320×823 → even below
    tw, th = tw // 2 * 2, th // 2 * 2
    n = 0
    step = 1 / 24
    for si, (frames, ended, crop) in enumerate(segments):
        seg = tmp / f"s{si}"
        seg.mkdir()
        i, k, t = 0, 0, frames[0][0]
        while t < ended:
            while k + 1 < len(frames) and frames[k + 1][0] <= t:
                k += 1
            (seg / f"{i:05}.jpg").write_bytes(frames[k][1])
            i, t = i + 1, t + step
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                                "-of", "csv=p=0", str(seg / "00000.jpg")], check=True, capture_output=True, text=True)
        kx = int(probe.stdout.strip()) / crop["vw"]
        cx, cy, cw, ch = (int(crop[key] * kx) // 2 * 2 for key in ("x", "y", "w", "h"))
        cw, ch = min(cw, tw), min(ch, th)
        vf = f"crop={cw}:{ch}:{cx}:{cy},pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color={pad_color}"
        run("ffmpeg", "-y", "-framerate", "24", "-i", str(seg / "%05d.jpg"), "-vf", vf,
            "-start_number", str(n), str(out_dir / "%05d.png"))
        n += i
    src = ["-framerate", "24", "-i", str(out_dir / "%05d.png"), "-an"]
    sizes, width = None, tw
    for width in (tw, 1188, 1056):
        scale = [] if width == tw else [f"scale={width}:-2"]
        vf = ",".join([*scale, "format=yuv420p"])
        for crf in (36, 40, 44, 48):
            run("ffmpeg", "-y", *src, "-vf", vf, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf), "-row-mt", "1",
                str(OUT / f"{name}.webm"))
            run("ffmpeg", "-y", *src, "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf - 8),
                "-movflags", "+faststart", str(OUT / f"{name}.mp4"))
            sizes = [(OUT / f"{name}.{ext}").stat().st_size for ext in ("webm", "mp4")]
            if max(sizes) <= CLIP_MAX_BYTES:
                break
        else:
            continue
        break
    else:
        raise SystemExit(f"{name}: still over {CLIP_MAX_BYTES} bytes at {width}px: {sizes}")
    poster = tmp / "poster.png"
    at = ["-ss", f"{poster_at:.2f}"] if poster_at is not None else ["-sseof", "-0.1"]
    run("ffmpeg", "-y", *at, "-i", str(OUT / f"{name}.mp4"), "-frames:v", "1", str(poster))
    run("cwebp", "-quiet", "-q", "80", str(poster), "-o", str(OUT / f"{name}-poster.webp"))
    gray = subprocess.run(["ffmpeg", "-v", "error", "-i", str(poster), "-vf", "scale=200:-1,format=gray", "-f", "rawvideo", "-"],
                          check=True, capture_output=True).stdout
    spread = statistics.pstdev(gray)
    if spread < 12:
        raise SystemExit(f"{name}: poster looks blank (luma stddev {spread:.1f})")
    shutil.rmtree(tmp)
    return {"frames": n, "width": width, "webm": sizes[0], "mp4": sizes[1], "poster_luma_sd": round(spread, 1)}


async def clip_know(p, report, nothing):
    """1. "Know this?" → "Not really" → "Noted, thanks." → the term inks in, one take (46d fix)."""
    await rec_view(p)
    await open_reader(p, "newcomer")
    await bring_to(p, ".rl-ask", 180)
    crop = await column_tile(p, 180 - 150)
    async def answer():
        await p.click_text(".rl-ask button", "Not really", 0.2)
    frames = await record(p, 0.8, answer, 3.6)  # refresh after 1.2 s, then the ink-in
    inked = await p.eval("!!document.querySelector('.rl-ask[data-state=done]') && document.querySelectorAll('.rl-mark:not(.rl-mark--ask)').length > 0")
    if not inked:
        raise SystemExit("clip-know: the term didn't ink in after Not really (is the 46d fix deployed?)")
    report["clip-know"] = encode_tiles([(*frames, crop)], "clip-know", pad_color=await paper_hex(p))


async def clip_note(p, report):
    """2. A fresh load: the paragraph plain, the highlights ink in; then the margin list filling."""
    await rec_view(p)
    await open_reader(p, "newcomer")
    first = await p.eval("""(() => { const m = document.querySelector('.rl-mark'); const r = m.getBoundingClientRect();
      return {y: r.top + scrollY}; })()""")
    if first["y"] > REC_H - 120:
        raise SystemExit("clip-note: no note in the first view at 680px")
    crop = await column_tile(p, first["y"] - 120)
    await p.eval("scrollTo(0, 0); true")

    seen = {}

    async def reload():
        # The clip starts once the article's text has painted (no blank page), before the marks.
        await p.send("Page.reload", ignoreCache=False)
        await wait_js(p, "!!document.querySelector('[data-rl-paragraph]')", 20)
        await asyncio.sleep(0.15)
        seen["t"] = time.time()
        seen["marks_at_start"] = await p.eval("document.querySelectorAll('.rl-mark').length")

    a = trim(await record(p, 0.2, reload, 3.4), seen)
    await rec_view(p, WIDE_W)
    await open_reader(p, "newcomer")
    rail = await p.eval(js_rect(".rail"))
    gutter_x = rail["x"] - 24
    rail_crop = {"x": int(gutter_x), "y": int(rail["y"]) - 16, "w": min(TILE_W, WIDE_W - int(gutter_x)), "h": TILE_H, "vw": WIDE_W}
    rail_crop["y"] = max(0, min(REC_H - TILE_H, rail_crop["y"]))
    b = trim(await record(p, 0.2, reload, 2.6), seen)
    report["clip-note-plain-start"] = seen.get("marks_at_start")
    report["clip-note"] = encode_tiles([(*a, crop), (*b, rail_crop)], "clip-note", poster_at=3.2, pad_color=await paper_hex(p))


def trim(recording, seen):
    """Drop frames before seen["t"]; the last earlier frame becomes the first, at seen["t"]."""
    frames, ended = recording
    t = seen["t"]
    before = [f for f in frames if f[0] <= t]
    after = [f for f in frames if f[0] > t]
    head = [(t, before[-1][1])] if before else []
    return head + after, ended


async def clip_simpler(p, report):
    """3. Tap a highlight → the card opens with the Background and analogy tag → "Say it simpler"."""
    await rec_view(p)
    await open_reader(p, "trader")
    await bring_to(p, '[data-rl-paragraph="p5"] .rl-mark', 120)
    term = await p.eval(mark_rect("tighter policy"))
    crop = await column_tile(p, term["y"] - 60)

    async def act():
        await click_mark(p, "tighter policy")
        await wait_js(p, READY)
        await asyncio.sleep(1.6)
        await p.click_text(".rl-card button", "Say it simpler", 0.3)
        await wait_js(p, READY, 60)

    frames = await record(p, 0.6, act, 1.6)
    report["clip-simpler"] = encode_tiles([(*frames, crop)], "clip-simpler", poster_at=2.0, pad_color=await paper_hex(p))


NODE_RECTS = """(labels => labels.map(l => { const g = [...document.querySelectorAll('.kmap__node')]
  .find(n => (n.getAttribute('aria-label') || '').startsWith(l)); if (!g) return null;
  const r = g.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; }).filter(Boolean))"""


async def clip_map(p, report, nothing):
    """4. The knowledge map with three ideas filling in (the "Know this? Yes" correction)."""
    await rec_view(p)
    overview = (await p.api(API, "GET", "/v1/me/graph?view=overview&persona=newcomer"))["body"]
    rings = [n for n in overview["nodes"] if n["ready"]][:3]
    labels = [n["label"] for n in rings]
    await p.goto(f"{WEB}/profile?persona=newcomer", wait=3)
    await wait_js(p, "!!document.querySelector('.kmap svg')", 60)
    await center(p, ".kmap")
    rects = await p.eval(f"{NODE_RECTS}({json.dumps(labels)})")
    box = union(*rects, pad=0, vw=REC_W, vh=REC_H) if rects else await p.eval(js_rect(".kmap"))
    crop = tile(box["x"] + box["w"] / 2 - TILE_W / 2, box["y"] + box["h"] / 2 - TILE_H / 2)
    a = await record(p, 0.2, nothing, 1.6)
    for n in rings:
        r = await p.api(API, "PATCH", f"/v1/me/graph/{n['id']}?persona=newcomer", {"state": "known"})
        report.setdefault("map_marked", []).append((n["label"], r["status"]))
    await p.goto(f"{WEB}/profile?persona=newcomer", wait=3)
    await wait_js(p, "!!document.querySelector('.kmap svg')", 60)
    await center(p, ".kmap")
    b = await record(p, 0.2, nothing, 2.4)
    report["clip-map"] = encode_tiles([(*a, crop), (*b, crop)], "clip-map", pad_color=await paper_hex(p))


def mark_rect(text):
    return f"""(() => {{ const m = [...document.querySelectorAll('.rl-mark')].find(m => m.textContent.trim() === {json.dumps(text)});
      const r = m.getBoundingClientRect(); return {{x: r.left, y: r.top, w: r.width, h: r.height}}; }})()"""


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
        if "--clips" in sys.argv:  # decision 46 P5: the four clips, no product shot
            only = ["clip-note", "clip-simpler", "clip-know", "clip-map"]
        if only is None or "product" in only:
            report["product"] = await product_shots(p, tmp)
        report["clips"] = await clips(p, only)
        if report["clips"]:
            names = ("clip-know", "clip-note", "clip-simpler", "clip-map")
            CROPS_FILE.write_text(json.dumps({"rec_width": REC_W, "body_px": 21,
                                              "crop_css_w": {n: TILE_W for n in names}}, indent=2) + "\n")
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
