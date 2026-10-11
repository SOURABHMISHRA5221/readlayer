"""Landing problem illustrations from Google's image model on Vertex (decision 44 V3).

    cd apps/api && uv run python -m scripts.landing_art --dry-run --out <dir>
    cd apps/api && uv run python -m scripts.landing_art --confirmed --out <dir>  # after his yes
    cd apps/api && uv run python -m scripts.landing_art --confirmed --out <dir> --reroll tabs

Every call goes through app.llm.generate_image (task `landing_art`, MODEL_IMAGE), so it is
budget-guarded and counted in production's ledger (ops/spend/days/{date}). The script counts
images itself and stops before a call that would pass MAX_IMAGES or CAP_USD (priced at
MODEL_IMAGE_PRICE_USD); it refuses to start if today's spend plus the cap would pass
LLM_DAILY_BUDGET_USD. The Margo reference is rasterised by headless Chrome to the output dir.
Outputs go to --out (a scratch directory, never the repo); the chosen ones are encoded by hand.
"""

import argparse
import asyncio
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app import llm
from app.config import get_settings

SCENES = {
    "jargon": (
        "Margo reading a page of dense text, frowning and confused; three words in the text "
        "are underlined in teal and a small question mark floats above Margo's head"
    ),
    "tabs": (
        "an open laptop with about a dozen browser tabs bursting out of the screen like loose "
        "cards flying in every direction; Margo stands beside it, overwhelmed"
    ),
    "shredder": (
        "a paper shredder: a full article page goes in at the top and only a short strip with "
        "three lines comes out at the bottom; Margo watches, worried"
    ),
}
VARIANTS = 2
MAX_REROLLS = 2
MAX_IMAGES = len(SCENES) * VARIANTS + MAX_REROLLS  # 8
CAP_USD = 0.60
REFERENCE_PX = 512
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MARGO_SVG = Path(__file__).resolve().parents[2] / "web/public/favicon.svg"


@dataclass
class Budget:
    """The run's own count: no call starts if it could pass the image or dollar cap."""

    price: float
    images: int = 0
    spent: float = 0.0

    def allows_another(self) -> bool:
        return self.images + 1 <= MAX_IMAGES and self.spent + self.price <= CAP_USD + 1e-9

    def charge(self, cost: float) -> None:
        self.images += 1
        self.spent += max(cost, self.price)  # never trust a lower reported price


def plan(reroll: str | None) -> list[tuple[str, int]]:
    if reroll:
        return [(reroll, VARIANTS + 1)]
    return [(scene, v) for scene in SCENES for v in range(1, VARIANTS + 1)]


def rasterise_margo(out: Path) -> bytes:
    """Margo on white at REFERENCE_PX square, via headless Chrome (not committed)."""
    page = Path(tempfile.mkdtemp()) / "margo.html"
    svg = MARGO_SVG.read_text()
    page.write_text(
        "<html><body style='margin:0;background:#fff;display:grid;place-items:center;"
        f"width:{REFERENCE_PX}px;height:{REFERENCE_PX}px'>"
        f"<div style='width:{REFERENCE_PX - 96}px'>{svg}</div></body></html>"
    )
    target = out / "margo-reference.png"
    subprocess.run(
        [CHROME, "--headless=new", "--hide-scrollbars", f"--screenshot={target}",
         f"--window-size={REFERENCE_PX},{REFERENCE_PX}", page.as_uri()],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    return target.read_bytes()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirmed", action="store_true", help="Sourabh said yes (AUTOPILOT_LOG)")
    ap.add_argument("--reroll", choices=sorted(SCENES))
    args = ap.parse_args()
    settings = get_settings()
    if not settings.model_image:
        print("MODEL_IMAGE is not set")
        return 1
    calls = plan(args.reroll)
    spent_today = await llm.get_spend_store().get_today()
    estimate = len(calls) * settings.model_image_price_usd
    print(
        f"model {settings.model_image}, {len(calls)} calls, estimate ${estimate:.2f} "
        f"(cap {MAX_IMAGES} images / ${CAP_USD:.2f}); production spend today "
        f"${spent_today:.4f} of ${settings.llm_daily_budget_usd:.2f}"
    )
    for scene, variant in calls:
        print(f"  {scene} v{variant}: {SCENES[scene]}")
    if spent_today + CAP_USD > settings.llm_daily_budget_usd:
        print("REFUSED: today's spend plus the cap would pass the daily budget")
        return 1
    if args.dry_run or not args.confirmed:
        print("dry run: nothing generated" if args.dry_run else "pass --confirmed after his yes")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    reference = rasterise_margo(args.out)
    budget = Budget(settings.model_image_price_usd)
    # One attempt per call: re-rolls are the only retries, so every paid call is counted here.
    once = settings.model_copy(update={"llm_max_retries": 0})
    made = []
    for scene, variant in calls:
        if not budget.allows_another():
            print(f"stopped at the cap: {budget.images} images, ${budget.spent:.2f}")
            break
        try:
            result = await llm.generate_image(
                "landing_art", {"scene": SCENES[scene]}, reference_png=reference, settings=once
            )
        except llm.LLMRejected as exc:  # the call was made and may have billed
            budget.charge(budget.price)
            print(f"  {scene} v{variant}: no usable image ({exc})")
            continue
        budget.charge(result.cost_usd)
        ext = "png" if result.mime == "image/png" else "jpg"
        path = args.out / f"{scene}-v{variant}.{ext}"
        path.write_bytes(result.data)
        made.append({"file": str(path), "size": [result.width, result.height],
                     "cost_usd": result.cost_usd, "attempts": result.attempts})  # fmt: skip
        print(f"  wrote {path.name} {result.width}x{result.height} ${result.cost_usd:.4f}")
    print(json.dumps({"model": settings.model_image, "prompt_version": "landing_art "
                      f"{llm.load_prompt('landing_art').version}", "images": made,
                      "spent_usd": round(budget.spent, 4)}, indent=2))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
