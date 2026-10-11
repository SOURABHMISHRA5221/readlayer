"""Landing media from the live site (decision 46e: full-window stills and loops in device frames).

    cd apps/api && uv run python -m scripts.landing_media_precheck      # read-only; run first
    uv run --project apps/api python tools/shots/landing_media.py --confirmed --stills --clips

As one temporary anonymous demo reader on the live site (deleted at the end with DELETE /v1/me,
which also deletes the Auth user): the full-window stills for "See it in action" (the reader with
the "bps" note, the For you feed, the phone sheet) and the four How it works loops. Writes
AVIF/WebP stills, WebM/MP4 loops (2x and 1x) with WebP posters to apps/web/public/landing/ and the
loops' focus boxes to apps/web/src/landing/clipFocus.json. The precheck prints the exact production
writes and refuses if anything would generate, search or build a feed.
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


# Decision 46e: device frames with HD full-window captures. Every still and loop is the whole
# Gloss window at a 1440×900 viewport and deviceScaleFactor 2 (2880×1800 frames), light theme, no
# crop; the phone still is 390×844 at DPR 2. Never upscaled: 2x files are native, 1x files are
# downscales. Loops ≤ 600 KB (2x, else the 1x encode ships as the large file too), a 1x encode
# for small screens, posters ≤ 120 KB. Each loop's area of action (fractions of the frame) goes to
# apps/web/src/landing/clipFocus.json for the tile's gentle zoom.
FULL_W, FULL_H, DPR = 1440, 900, 2
PHONE_W, PHONE_H = 390, 844
LOOP_MAX = 600_000
POSTER_MAX = 120_000
STILL_MAX = {1: 120_000, 2: 250_000}
FOCUS_FILE = Path(__file__).resolve().parents[2] / "apps/web/src/landing/clipFocus.json"


async def view(p, width=FULL_W, height=FULL_H, mobile=False):
    await p.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=DPR, mobile=mobile)


async def light(p):
    await p.eval("localStorage.setItem('readlayer:theme', 'light'); document.documentElement.dataset.theme = 'light'; true")


async def capture(p, path: Path) -> Path:
    r = await p.send("Page.captureScreenshot", format="png")
    path.write_bytes(cdp.base64.b64decode(r["data"]))
    return path


def png_width(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    return int(out.stdout.strip())


def encode_still(png: Path, name: str, css_w: int) -> dict:
    """1x (downscaled) and 2x (native) AVIF + WebP within STILL_MAX; refuses an upscale."""
    if png_width(png) < css_w * DPR:
        raise SystemExit(f"{name}: capture narrower than {css_w * DPR}px, would need an upscale")
    sizes = {}
    for scale, suffix in ((1, ""), (2, "@2x")):
        w = css_w * scale
        for q in (80, 72, 64, 56):
            webp = OUT / f"{name}{suffix}.webp"
            run("cwebp", "-quiet", "-q", str(q), "-resize", str(w), "0", str(png), "-o", str(webp))
            if webp.stat().st_size <= STILL_MAX[scale]:
                break
        for crf in (34, 40, 46):
            avif = OUT / f"{name}{suffix}.avif"
            run("ffmpeg", "-y", "-i", str(png), "-vf", f"scale={w}:-2,format=yuv420p", "-c:v", "libsvtav1",
                "-crf", str(crf), "-frames:v", "1", str(avif))
            if avif.stat().st_size <= STILL_MAX[scale]:
                break
        sizes[f"{scale}x"] = {"webp": webp.stat().st_size, "avif": avif.stat().st_size}
        if max(sizes[f"{scale}x"].values()) > STILL_MAX[scale]:
            raise SystemExit(f"{name} {scale}x over {STILL_MAX[scale]} bytes: {sizes[f'{scale}x']}")
    return sizes


async def stills(p, tmp: Path, report):
    """See it in action: the reader with the bps note open, the For you feed, the phone sheet."""
    await view(p)
    await light(p)
    await open_reader(p, "newcomer")
    await center(p, '[data-rl-paragraph="p5"]')
    await click_mark(p, "bps")
    await wait_js(p, READY)
    await asyncio.sleep(0.8)
    report["shot-reader"] = encode_still(await capture(p, tmp / "reader.png"), "shot-reader", FULL_W)

    await p.goto(f"{WEB}/for-you?persona=newcomer", wait=3)
    await wait_js(p, "document.querySelectorAll('article.row').length >= 4", 40)
    await asyncio.sleep(1.5)  # thumbnails
    report["shot-feed"] = encode_still(await capture(p, tmp / "feed.png"), "shot-feed", FULL_W)

    await view(p, PHONE_W, PHONE_H, mobile=True)
    await open_reader(p, "newcomer")
    await center(p, '[data-rl-paragraph="p5"]')
    await click_mark(p, "bps")
    await wait_js(p, READY)
    await asyncio.sleep(0.8)
    report["shot-phone"] = encode_still(await capture(p, tmp / "phone.png"), "shot-phone", PHONE_W)


async def record(p, seconds_before, action, seconds_after):
    rec = cdp.Recorder()
    await rec.start()
    await asyncio.sleep(seconds_before)
    await action()
    await asyncio.sleep(seconds_after)
    frames = await rec.stop()
    return frames, rec.ended  # 2880×1800 frames: Chrome runs at device scale 2 (cdp.launch(scale=2))


def trim(recording, t):
    """Drop frames before t; the last earlier frame becomes the first, at t."""
    frames, ended = recording
    before = [f for f in frames if f[0] <= t]
    after = [f for f in frames if f[0] > t]
    return ([(t, before[-1][1])] if before else []) + after, ended


def encode_loop(segments, name: str, poster_at: float | None = None) -> dict:
    """Full frames (one or more takes, hard cuts) → name.webm/.mp4 (2x if ≤ LOOP_MAX, else the 1x
    encode), name-1x.webm/.mp4 for small screens, and a WebP poster ≤ POSTER_MAX."""
    tmp = Path(tempfile.mkdtemp(prefix="gloss-loop-"))
    i, step = 0, 1 / 24
    for frames, ended in segments:
        k, t = 0, frames[0][0]
        while t < ended:
            while k + 1 < len(frames) and frames[k + 1][0] <= t:
                k += 1
            (tmp / f"{i:05}.jpg").write_bytes(frames[k][1])
            i, t = i + 1, t + step
    native = png_width(tmp / "00000.jpg")
    src = ["-framerate", "24", "-i", str(tmp / "%05d.jpg"), "-an"]

    def encode(width: int, out: str) -> list[int] | None:
        scale = "" if width >= native else f"scale={width}:-2,"
        for crf in (34, 38, 42, 46, 50):
            run("ffmpeg", "-y", *src, "-vf", f"{scale}format=yuv420p", "-c:v", "libvpx-vp9", "-b:v", "0",
                "-crf", str(crf), "-row-mt", "1", str(OUT / f"{out}.webm"))
            run("ffmpeg", "-y", *src, "-vf", f"{scale}format=yuv420p", "-c:v", "libx264", "-preset", "slow",
                "-crf", str(crf - 10), "-movflags", "+faststart", str(OUT / f"{out}.mp4"))
            sizes = [(OUT / f"{out}.{ext}").stat().st_size for ext in ("webm", "mp4")]
            if max(sizes) <= LOOP_MAX:
                return sizes
        return None

    small = encode(FULL_W, f"{name}-1x")
    if small is None:
        raise SystemExit(f"{name}: even the 1x encode is over {LOOP_MAX} bytes")
    large = encode(native, name)
    shipped = native
    if large is None:  # the 2x doesn't fit: the 1x encode is the large file too (a downscale)
        for ext in ("webm", "mp4"):
            shutil.copy(OUT / f"{name}-1x.{ext}", OUT / f"{name}.{ext}")
        large, shipped = small, FULL_W
    poster = tmp / "poster.png"
    at = ["-ss", f"{poster_at:.2f}"] if poster_at is not None else ["-sseof", "-0.3"]
    run("ffmpeg", "-y", *at, "-i", str(OUT / f"{name}-1x.mp4"), "-frames:v", "1", str(poster))
    for q in (78, 70, 62, 54):
        run("cwebp", "-quiet", "-q", str(q), str(poster), "-o", str(OUT / f"{name}-poster.webp"))
        if (OUT / f"{name}-poster.webp").stat().st_size <= POSTER_MAX:
            break
    else:
        raise SystemExit(f"{name}: poster over {POSTER_MAX} bytes")
    gray = subprocess.run(["ffmpeg", "-v", "error", "-i", str(poster), "-vf", "scale=200:-1,format=gray", "-f", "rawvideo", "-"],
                          check=True, capture_output=True).stdout
    if statistics.pstdev(gray) < 12:
        raise SystemExit(f"{name}: poster looks blank")
    shutil.rmtree(tmp)
    return {"frames": i, "shipped_width": shipped, "webm": large[0], "mp4": large[1], "webm_1x": small[0],
            "mp4_1x": small[1], "poster": (OUT / f"{name}-poster.webp").stat().st_size}


def fraction(*rects, pad=60) -> dict:
    box = union(*rects, pad=pad, vw=FULL_W, vh=FULL_H)
    return {k: round(v, 4) for k, v in
            {"x": box["x"] / FULL_W, "y": box["y"] / FULL_H, "w": box["w"] / FULL_W, "h": box["h"] / FULL_H}.items()}


def mark_rect(text):
    return f"""(() => {{ const m = [...document.querySelectorAll('.rl-mark')].find(m => m.textContent.trim() === {json.dumps(text)});
      const r = m.getBoundingClientRect(); return {{x: r.left, y: r.top, w: r.width, h: r.height}}; }})()"""


async def clip_know(p, report, focus):
    """1. "Know this?" → "Not really" → "Noted, thanks." → the term inks in, one take (46d fix)."""
    await open_reader(p, "newcomer")
    await p.eval("document.querySelector('.rl-ask').scrollIntoView({block: 'center'}); true")
    await asyncio.sleep(1.2)
    focus["clip-know"] = fraction(await p.eval(js_rect(".rl-mark--ask")), await p.eval(js_rect(".rl-ask")), pad=140)
    frames = await record(p, 0.8, lambda: p.click_text(".rl-ask button", "Not really", 0.2), 3.8)
    inked = await p.eval("!!document.querySelector('.rl-ask[data-state=done]') && document.querySelectorAll('.rl-mark:not(.rl-mark--ask)').length > 0")
    if not inked:
        raise SystemExit("clip-know: the term didn't ink in after Not really")
    report["clip-know"] = encode_loop([frames], "clip-know")


async def clip_note(p, report, focus):
    """2. The paragraphs plain, then the highlights ink in while the margin list fills: a reload,
    and as soon as the text paints (before the notes arrive) the view jumps to the first noted
    paragraph; the frames before the jump are trimmed, so the loop opens on plain text."""
    await open_reader(p, "newcomer")
    target = await p.eval("""(() => { const para = document.querySelector('.rl-mark').closest('[data-rl-paragraph]');
      return Math.max(0, para.getBoundingClientRect().top + scrollY - 220); })()""")
    await p.eval(f"scrollTo(0, {target}); true")
    await asyncio.sleep(1.0)
    para = await p.eval("""(() => { const r = document.querySelector('.rl-mark').closest('[data-rl-paragraph]').getBoundingClientRect();
      return {x: r.left, y: r.top, w: r.width, h: r.height}; })()""")
    rail = await p.eval(js_rect(".rail"))
    focus["clip-note"] = fraction(para, {**rail, "y": max(rail["y"], 0), "h": min(rail["h"], 360)}, pad=40)
    seen = {}

    async def reload():
        await p.send("Page.reload", ignoreCache=False)
        await wait_js(p, "!!document.querySelector('[data-rl-paragraph]')", 20)
        await p.eval(f"scrollTo(0, {target}); true")
        await asyncio.sleep(0.12)
        seen["t"] = time.time()
        seen["marks_at_start"] = await p.eval("document.querySelectorAll('.rl-mark').length")

    # A slower network for this take (the text arrives first, the notes after it), as a reader
    # on a phone connection sees it; cached app files aren't affected.
    await p.send("Network.enable")
    await p.send("Network.emulateNetworkConditions", offline=False, latency=700, downloadThroughput=-1, uploadThroughput=-1)
    try:
        rec = await record(p, 0.2, reload, 4.2)
    finally:
        await p.send("Network.emulateNetworkConditions", offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)
    seen["marks_at_end"] = await p.eval("document.querySelectorAll('.rl-mark').length")
    report["clip-note-marks"] = {"start": seen["marks_at_start"], "end": seen["marks_at_end"]}
    if seen["marks_at_start"] >= seen["marks_at_end"]:
        raise SystemExit(f"clip-note: the notes were already in when the loop starts {report['clip-note-marks']}")
    report["clip-note"] = encode_loop([trim(rec, seen["t"])], "clip-note")


async def clip_simpler(p, report, focus):
    """3. Tap a highlight → the card opens with the Background and analogy tag → "Say it simpler"."""
    await open_reader(p, "trader")
    await center(p, '[data-rl-paragraph="p5"]')
    term = await p.eval(mark_rect("tighter policy"))
    marks = {}

    async def act():
        await click_mark(p, "tighter policy")
        await wait_js(p, READY)
        marks["opened"] = time.time()
        marks["card"] = await p.eval(js_rect(".rl-card:not([hidden])"))
        await asyncio.sleep(1.8)
        await p.click_text(".rl-card button", "Say it simpler", 0.3)
        await wait_js(p, READY, 60)

    start = time.time()
    frames = await record(p, 0.6, act, 1.8)
    focus["clip-simpler"] = fraction(term, marks["card"], pad=40)
    report["clip-simpler"] = encode_loop([frames], "clip-simpler", poster_at=marks["opened"] - start + 0.9)


NODE_RECTS = """(labels => labels.map(l => { const g = [...document.querySelectorAll('.kmap__node')]
  .find(n => (n.getAttribute('aria-label') || '').startsWith(l)); if (!g) return null;
  const r = g.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; }).filter(Boolean))"""


async def clip_map(p, report, focus):
    """4. The profile's knowledge map with three ideas filling in (the "Know this? Yes" correction)."""
    overview = (await p.api(API, "GET", "/v1/me/graph?view=overview&persona=newcomer"))["body"]
    rings = [n for n in overview["nodes"] if n["ready"]][:3]
    labels = [n["label"] for n in rings]
    await p.goto(f"{WEB}/profile?persona=newcomer", wait=3)
    await wait_js(p, "!!document.querySelector('.kmap svg')", 60)
    await center(p, ".kmap")
    rects = await p.eval(f"{NODE_RECTS}({json.dumps(labels)})")
    focus["clip-map"] = fraction(*rects, pad=90) if rects else fraction(await p.eval(js_rect(".kmap")), pad=0)
    a = await record(p, 0.2, nothing, 1.6)
    for n in rings:
        r = await p.api(API, "PATCH", f"/v1/me/graph/{n['id']}?persona=newcomer", {"state": "known"})
        report.setdefault("map_marked", []).append((n["label"], r["status"]))
    await p.goto(f"{WEB}/profile?persona=newcomer", wait=3)
    await wait_js(p, "!!document.querySelector('.kmap svg')", 60)
    await center(p, ".kmap")
    b = await record(p, 0.2, nothing, 2.4)
    report["clip-map"] = encode_loop([a, b], "clip-map")


async def nothing():
    return None


async def clips(p, report, only=None):
    await view(p)
    await light(p)
    focus = json.loads(FOCUS_FILE.read_text())["clips"] if FOCUS_FILE.exists() else {}
    steps = (("clip-know", clip_know), ("clip-note", clip_note), ("clip-simpler", clip_simpler), ("clip-map", clip_map))
    for name, step in steps:  # the landing's order: 1 → 4
        if only is None or name in only:
            try:
                await step(p, report, focus)
            except SystemExit as e:  # one clip's failure doesn't cost the run the others
                report.setdefault("failed", {})[name] = str(e)
                continue
            FOCUS_FILE.write_text(json.dumps({"clips": focus}, indent=2) + "\n")


async def main():
    if "--confirmed" not in sys.argv:
        raise SystemExit("Run `uv run python -m scripts.landing_media_precheck` (in apps/api) first, then pass --confirmed.")
    want_stills, want_clips = "--stills" in sys.argv, "--clips" in sys.argv
    if not (want_stills or want_clips):
        raise SystemExit("pass --stills and/or --clips")
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), None)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="gloss-media-"))
    cdp.launch(scale=2)
    p, ws = await cdp.open_page()
    report = {}
    try:
        await p.viewport(1440)
        await cdp.Page.reset_auth(p, WEB)
        await p.goto(WEB + "/", wait=4)
        # The live front door: the landing's demo CTA after the Landing milestone ships, the
        # persona picker before it.
        if not await p.click_text("button", "Newcomer", 5):
            raise SystemExit("no Newcomer button on the live front door")
        if want_stills:
            await stills(p, tmp, report)
        if want_clips:
            await clips(p, report, only)
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
