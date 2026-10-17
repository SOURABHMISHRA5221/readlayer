"""Decision 70 PR A on the local harness: "For you" after 10 engaged articles (Fix 1) and the ¶
paragraph notes counted and listed (Fix 2). One demo reader (landing CTA), as the trader:

- the Guardian library article: the margin heading counts words + ¶ notes, ¶ items are listed
  and open their paragraph card; the 390 px drawer says the same count;
- a word's card: no analogy toggle and "Your pick · Cricket" (0 engaged);
- after 10 paragraph-dwell events on 10 library articles: the toggle is back.

    make dev-emulator   # in another terminal
    SHOTS_OUT=docs/evidence/d70 uv run --project apps/api python tools/shots/d70.py

Emulators only; the reader is deleted at the end. Explain calls are real (capped, cents).
"""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

W = "http://localhost:5173"
API = ""  # the web dev server proxies /v1 to the harness API
GUARDIAN = "99a2cb53f16256bd275bafd180364134"
CARD_READY = "document.querySelector('.rl-card__frame:not([hidden]), .rl-frame:not([hidden])')"

STATE_JS = """(() => ({
  head: document.querySelector('.rail__head')?.textContent.trim() ?? null,
  items: [...document.querySelectorAll('.rail__item')].map(b => [b.dataset.kind, b.textContent.trim()]),
  marks: new Set([...document.querySelectorAll('.rl-mark[data-rl-id]')].map(m => m.dataset.rlId)).size,
  pmarks: document.querySelectorAll('.rl-pmark').length,
  spine: document.querySelector('.spine__count')?.textContent.trim() ?? null,
  drawer: document.querySelector('.drawer__toggle')?.textContent.trim() ?? null,
}))()"""

CARD_JS = """(() => {
  const c = document.querySelector('.rl-card');
  const g = c?.querySelector('.rl-frame');
  const f = c?.querySelector('.rl-card__frame');
  return {
    title: c?.querySelector('.rl-card__title, h2')?.textContent.trim() ?? null,
    toggle: g && !g.hidden ? [...g.querySelectorAll('button')].map(b => b.textContent) : null,
    label: f && !f.hidden ? f.textContent : null,
    background: c?.querySelector('.rl-card__bg')?.textContent.slice(0, 160) ?? null,
  };
})()"""


async def open_reader(p, width: int) -> dict:
    await p.viewport(width)
    await p.goto(f"{W}/read/{GUARDIAN}?persona=trader", wait=2)
    await p.wait_for(".rl-pmark", 60)
    await asyncio.sleep(1.5)
    return await p.eval(STATE_JS)


async def open_first_word_card(p) -> dict:
    await p.eval("document.querySelector('.rail__item:not([data-kind=paragraph])').click(); 1")
    for _ in range(90):
        if await p.eval(f"!!{CARD_READY}"):
            break
        await asyncio.sleep(1)
    return await p.eval(CARD_JS)


async def offered(p) -> dict:
    """The frames the API offers on each of the trader's word notes (pick Backgrounds, cached)."""
    notes = (await p.api(API, "GET", f"/v1/content/{GUARDIAN}/annotations?persona=trader&refresh=1"))["body"]
    out = {}
    for a in [a for a in notes["annotations"] if a["kind"] == "span"]:
        body = {"content_id": GUARDIAN, "demand_id": a["id"]}
        got = (await p.api(API, "POST", "/v1/explain?persona=trader", body))["body"] or {}
        out[a["label"]] = (a.get("domain"), (got.get("frames") or {}).get("for_you"))
    return out


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    out: dict = {}
    try:
        await p.viewport(1440)
        await cdp.Page.reset_auth(p, W)
        await p.goto(W + "/", wait=4)
        await p.wait_for(".lp-nav__cta", 30)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")  # Try the demo
        await asyncio.sleep(6)

        out["wide"] = await open_reader(p, 1440)
        await p.shot("d70-margin-1440")
        await p.eval("document.querySelector('.rail__item[data-kind=paragraph]')?.click(); 1")
        await asyncio.sleep(1)
        out["paragraph_card"] = await p.eval(
            "document.querySelector('.rl-card')?.textContent.includes('What this paragraph is saying')"
        )
        await p.eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); 1")
        await asyncio.sleep(0.5)
        out["card_before"] = await open_first_word_card(p)
        await p.shot("d70-card-before-1440")

        out["phone"] = await open_reader(p, 390)
        await p.shot("d70-drawer-390")

        out["offered_before"] = await offered(p)
        lib = (await p.api(API, "GET", "/v1/content?persona=trader"))["body"]
        ids = [i["id"] for i in lib if i["id"] != GUARDIAN][:10]
        # The harness library is small: pad with content ids the events route records as engaged.
        ids += [f"d70-content-{i}" for i in range(10 - len(ids))]
        now = datetime.now(UTC).isoformat()
        events = [
            {"id": f"d70-{i}-{int(time.time())}", "type": "paragraph_dwell", "at": now,
             "content_id": cid, "paragraph_id": "p0", "words": 40}
            for i, cid in enumerate(ids)
        ]  # fmt: skip
        out["events"] = (await p.api(API, "POST", "/v1/events", {"persona": "trader", "events": events}))["body"]
        out["engaged_sent"] = len(ids)

        out["offered_after"] = await offered(p)
        out["wide_after"] = await open_reader(p, 1440)
        out["card_after"] = await open_first_word_card(p)
        await p.shot("d70-card-after-1440")
    finally:
        try:
            if not os.environ.get("D70_KEEP"):  # debugging only: keep the emulator reader
                out["cleanup"] = (await p.api(API, "DELETE", "/v1/me"))["status"]
        finally:
            await ws.close()
            cdp.stop()
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
