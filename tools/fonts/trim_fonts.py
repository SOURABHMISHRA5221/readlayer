"""Self-hosted, trimmed web fonts (decision 47).

    uv run --with fonttools==4.60.1 --with brotli==1.1.0 python tools/fonts/trim_fonts.py

Downloads the pinned Fontsource variable packages (npm registry tarballs), takes the Latin `wght`
files only and limits their weight axis to the weights the app uses, then writes WOFF2 files and
the OFL licence to apps/web/public/fonts/. Fontsource's Latin subset has no rupee sign, so each
face also gets a one-glyph file (U+20B9, from its latin-ext file), declared with its own
unicode-range in fonts.css and fetched only where ₹ appears. File names carry VERSION, so the
Hosting cache can be immutable. Prints input and output sizes. No runtime dependency.
"""

import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "apps/web/public/fonts"
PACKAGES = {
    "@fontsource-variable/schibsted-grotesk": "5.3.0",
    "@fontsource-variable/source-serif-4": "5.3.1",
}
VERSION = "v1"  # bump when the files change (the URLs are cached as immutable)
RUPEE = 0x20B9
# (package, face file stem, output stem, weight range): what the app uses (decision 47).
FACES = (
    ("@fontsource-variable/schibsted-grotesk", "schibsted-grotesk-{s}-wght-normal", "schibsted-grotesk", (400, 800)),
    ("@fontsource-variable/source-serif-4", "source-serif-4-{s}-wght-normal", "source-serif-4", (400, 600)),
    ("@fontsource-variable/source-serif-4", "source-serif-4-{s}-wght-italic", "source-serif-4-italic", (400, 500)),
)


def trimmed(src: Path, lo: int, hi: int, only: int | None = None) -> bytes:
    font = TTFont(io.BytesIO(src.read_bytes()))
    if "opsz" in {a.axisTag for a in font["fvar"].axes}:
        raise SystemExit(f"{src.name}: unexpected opsz axis")
    if only is not None:
        if only not in font.getBestCmap():
            raise SystemExit(f"{src.name}: no U+{only:04X}")
        options = subset.Options()
        options.layout_features = ["*"]
        sub = subset.Subsetter(options)
        sub.populate(unicodes=[only])
        sub.subset(font)
    font = instancer.instantiateVariableFont(font, {"wght": (lo, hi)})
    font.flavor = "woff2"
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def fetch(package: str, version: str, into: Path) -> Path:
    out = subprocess.run(["npm", "pack", f"{package}@{version}", "--silent"], cwd=into, check=True,
                         capture_output=True, text=True).stdout.strip().splitlines()[-1]
    dest = into / package.replace("/", "_")
    with tarfile.open(into / out) as tar:
        tar.extractall(dest, filter="data")
    return dest / "package"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"packages": PACKAGES, "files": {}}
    with tempfile.TemporaryDirectory() as tmp:
        roots = {p: fetch(p, v, Path(tmp)) for p, v in PACKAGES.items()}
        for old in OUT.glob("*.woff2"):
            old.unlink()
        for package, stem, out_stem, (lo, hi) in FACES:
            files = roots[package] / "files"
            for subset_name, suffix, only in (("latin", "latin", None), ("latin-ext", "rupee", RUPEE)):
                src = files / f"{stem.format(s=subset_name)}.woff2"
                data = trimmed(src, lo, hi, only)
                out_name = f"{out_stem}-{suffix}-{VERSION}.woff2"
                (OUT / out_name).write_bytes(data)
                report["files"][out_name] = {"from": f"{package}/files/{src.name}", "wght": [lo, hi],
                                             "in_bytes": src.stat().st_size, "out_bytes": len(data)}
        licence = roots["@fontsource-variable/source-serif-4"] / "LICENSE"
        (OUT / "OFL.txt").write_text(
            "Schibsted Grotesk and Source Serif 4, via Fontsource. Both under the SIL Open Font "
            "License 1.1:\n\n" + licence.read_text()
        )
    (OUT / "fonts.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
