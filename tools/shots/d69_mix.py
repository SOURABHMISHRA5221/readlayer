"""Decision 69 G on the local harness: screen 2's cards share the chosen formats equally. A fresh
account (Auth-emulator "Google") chooses Read + Listen and three topics, then polls
POST /v1/onboarding/discover until it settles and prints the formats served, in order.

    make dev-emulator   # in another terminal
    uv run --project apps/api python tools/shots/d69_mix.py

Emulators only; the account is deleted at the end. Search calls are real (capped).
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

W = "http://localhost:5173"
EMAIL = f"d69-mix-{int(time.time())}@example.com"
TOPICS = ["economics", "sports", "business"]


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    out: dict = {}
    try:
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.eval(f"window.__rlEmulatorSignIn({json.dumps(EMAIL)}, 'Mix Check')")
        await asyncio.sleep(4)
        await p.api("", "POST", "/v1/me/consent", {"version": "consent-v2"})
        body = {"field": "software", "interests": TOPICS, "thinks_in": ["software"],
                "country": "IN", "formats": ["article", "podcast"]}  # fmt: skip
        out["onboarding"] = (await p.api("", "POST", "/v1/onboarding", body))["status"]
        t0 = time.monotonic()
        got: dict = {}
        while time.monotonic() - t0 < 90:
            got = (await p.api("", "POST", "/v1/onboarding/discover",
                               {"topics": TOPICS, "concepts": []}))["body"]  # fmt: skip
            if not got.get("pending"):
                break
            await asyncio.sleep(3)
        fmts = [i["format"] for i in got.get("items", [])]
        out["after_s"] = round(time.monotonic() - t0, 1)
        out["pending"] = got.get("pending")
        out["order"] = fmts
        out["counts"] = {f: fmts.count(f) for f in ("article", "podcast", "video")}
        out["topics"] = [i["topic"] for i in got.get("items", [])]
        await p.goto(W + "/welcome", wait=3)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 40)
        await asyncio.sleep(2)
        print("[shot]", await p.shot("d69-screen2-read-listen-1440-light", full=True))
    finally:
        out["delete"] = (await p.api("", "DELETE", "/v1/me"))["status"]
        print(json.dumps(out, indent=1))
        dest = Path(os.environ.get("SHOTS_OUT", "docs/evidence/d69")) / "d69_mix.json"
        dest.write_text(json.dumps(out, indent=1) + "\n")
        await ws.close()
        cdp.stop()


asyncio.run(main())
