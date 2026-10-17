"""Decision 70 PR B on the local harness (or live with D70_LIVE=1): explain a selection. One demo
reader (landing CTA), as the trader on the Guardian article:

- select "insider trading" (extracted, not marked for the trader) → Explain → its card, verified,
  and the margin count goes up by one;
- select a plain phrase with no term → the paragraph's card;
- keyboard: the button is a <button> in the paragraph, Enter on it opens the card;
- 390 px: the button shows on screen and opens the bottom sheet.

    make dev-emulator   # in another terminal
    SHOTS_OUT=docs/evidence/d70 uv run --project apps/api python tools/shots/d70_select.py

The reader is deleted at the end. Explain calls are real (capped, cents).
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

LIVE = bool(os.environ.get("D70_LIVE"))
W = "https://glossreader.web.app" if LIVE else "http://localhost:5173"
API = "https://readlayer-api-751104670850.asia-south1.run.app" if LIVE else ""
GUARDIAN = "99a2cb53f16256bd275bafd180364134"

SELECT_JS = """((part) => {
  for (const p of document.querySelectorAll('[data-rl-paragraph]')) {
    const w = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const at = n.data.indexOf(part);
      if (at < 0) continue;
      const r = document.createRange();
      r.setStart(n, at); r.setEnd(n, at + part.length);
      const s = document.getSelection(); s.removeAllRanges(); s.addRange(r);
      p.scrollIntoView({block: 'center'});
      document.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
      const b = document.querySelector('.rl-select');
      if (!b) return {button: false};
      const box = b.getBoundingClientRect();
      return {button: true, inParagraph: b.parentElement === p, tag: b.tagName,
              onScreen: box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight};
    }
  }
  return {button: false, missing: true};
})"""

CARD_JS = """(() => {
  const c = document.querySelector('.rl-card');
  if (!c || c.hidden || getComputedStyle(c).display === 'none') return null;
  return {
    mode: c.dataset.mode ?? null,
    text: c.textContent.slice(0, 220),
    verified: !!c.querySelector('.rl-card__says:not([hidden]) .rl-card__text')?.textContent,
  };
})()"""

COUNT_JS = "document.querySelector('.rail__head')?.textContent.trim() ?? null"


async def card(p, want: str = "", timeout: int = 90):
    for _ in range(timeout):
        got = await p.eval(CARD_JS)
        if got and got["verified"] and want in got["text"]:
            return got
        await asyncio.sleep(1)
    return await p.eval(CARD_JS)


async def close(p):
    await p.eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); 1")
    await asyncio.sleep(0.6)


async def main() -> None:
    cdp.launch()
    p, ws = await cdp.open_page()
    out: dict = {"live": LIVE}
    try:
        await p.viewport(1440)
        await cdp.Page.reset_auth(p, W)
        await p.goto(W + "/", wait=4)
        await p.wait_for(".lp-nav__cta", 30)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")  # Try the demo
        await asyncio.sleep(6)
        await p.goto(f"{W}/read/{GUARDIAN}?persona=trader", wait=2)
        await p.wait_for(".rail__item", 60)
        await asyncio.sleep(1.5)
        out["count_before"] = await p.eval(COUNT_JS)

        out["term_select"] = await p.eval(f"{SELECT_JS}('insider trading')")
        await asyncio.sleep(0.4)  # past the 120 ms fade-in
        await p.shot("d70-select-button-1440")
        await p.eval("document.querySelector('.rl-select').click(); 1")
        out["term_card"] = await card(p, "Insider")
        await asyncio.sleep(1)
        out["count_after"] = await p.eval(COUNT_JS)
        await p.shot("d70-select-card-1440")
        await close(p)

        out["plain_select"] = await p.eval(f"{SELECT_JS}('growing concerns')")
        await p.eval("document.querySelector('.rl-select').click(); 1")
        out["plain_card"] = await card(p, "What this paragraph is saying")
        await close(p)

        # Keyboard: focus the button, then a real Enter key press.
        out["key_select"] = await p.eval(f"{SELECT_JS}('market manipulation')")
        await p.eval("document.querySelector('.rl-select').focus(); 1")
        for kind in ("keyDown", "keyUp"):
            await p.send("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter",
                         windowsVirtualKeyCode=13, text="\r" if kind == "keyDown" else "")  # fmt: skip
        out["key_card"] = await card(p)
        await close(p)

        await p.viewport(390)
        await p.goto(f"{W}/read/{GUARDIAN}?persona=trader", wait=2)
        await p.wait_for(".rl-pmark", 60)
        await asyncio.sleep(1.5)
        out["phone_select"] = await p.eval(f"{SELECT_JS}('insider trading')")
        await asyncio.sleep(0.4)
        await p.shot("d70-select-button-390")
        await p.eval("document.querySelector('.rl-select').click(); 1")
        out["phone_card"] = await card(p, "Insider")
        await p.shot("d70-select-sheet-390")
    finally:
        try:
            out["cleanup"] = (await p.api(API, "DELETE", "/v1/me"))["status"]
        finally:
            await ws.close()
            cdp.stop()
            print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
