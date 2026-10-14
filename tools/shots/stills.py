"""Landing stills (decision 46e): a native 2x capture encoded as 1x (downscaled) and 2x AVIF + WebP
into apps/web/public/landing/, each within STILL_MAX; never upscaled. Shared by landing_media.py
and landing_extension.py (decision 61)."""

import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "apps/web/public/landing"
DPR = 2
STILL_MAX = {1: 120_000, 2: 250_000}


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def png_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    w, h = out.stdout.strip().split(",")
    return int(w), int(h)


def png_width(path: Path) -> int:
    return png_size(path)[0]


def encode_still(png: Path, name: str, css_w: int) -> dict:
    """1x (downscaled) and 2x (native) AVIF + WebP within STILL_MAX; refuses an upscale."""
    if png_width(png) < css_w * DPR:
        raise SystemExit(f"{name}: capture narrower than {css_w * DPR}px, would need an upscale")
    sizes = {}
    for scale, suffix in ((1, ""), (2, "@2x")):
        w = css_w * scale
        for q in (80, 72, 64, 56, 48, 40):  # text-heavy pages (Wikipedia) need the low end
            webp = OUT / f"{name}{suffix}.webp"
            run("cwebp", "-quiet", "-q", str(q), "-resize", str(w), "0", str(png), "-o", str(webp))
            if webp.stat().st_size <= STILL_MAX[scale]:
                break
        for crf in (34, 40, 46, 52):
            avif = OUT / f"{name}{suffix}.avif"
            run("ffmpeg", "-y", "-i", str(png), "-vf", f"scale={w}:-2,format=yuv420p", "-c:v", "libsvtav1",
                "-crf", str(crf), "-frames:v", "1", str(avif))
            if avif.stat().st_size <= STILL_MAX[scale]:
                break
        sizes[f"{scale}x"] = {"webp": webp.stat().st_size, "avif": avif.stat().st_size}
        if max(sizes[f"{scale}x"].values()) > STILL_MAX[scale]:
            raise SystemExit(f"{name} {scale}x over {STILL_MAX[scale]} bytes: {sizes[f'{scale}x']}")
    return sizes
