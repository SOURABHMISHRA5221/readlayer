"""Onboarding in 2 screens (decisions 41, 68) on the local harness: screenshots, axe, target sizes,
the timed flow and the feed-order check. Emulators only; ≤ 18 topic + ≤ 2 concept searches.

    SHOTS_OUT=docs/evidence/onboarding/after uv run --project apps/api python tools/shots/onboarding.py
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
from landing import press, tab_to  # noqa: E402

W = "http://localhost:5173"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))
EMAIL = "onboarding-check@example.com"


async def theme(p, dark):
    await p.eval(f"localStorage.setItem('readlayer:theme', '{'dark' if dark else 'light'}'); 1")


async def check(p, name, ready, full=True):
    for w, dark in SIZES:
        await p.viewport(w, dark=dark)
        await theme(p, dark)
        await p.goto(W + "/welcome", wait=1)
        ok = await p.wait_for(ready, 40)
        await asyncio.sleep(1.5)
        a = await p.audit()
        tag = f"{w}-{'dark' if dark else 'light'}"
        shot = await p.shot(f"{name}-{tag}", full=full)
        print(f"[{name} {tag}] ready={ok} axe={a['axe']} hscroll={a['hscroll']} small={json.dumps(a['small'])[:200]} {shot}")


async def type_text(p, selector, value):
    await p.eval(f"""(() => {{ const el = document.querySelector({json.dumps(selector)});
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, {json.dumps(value)});
      el.dispatchEvent(new Event('input', {{bubbles: true}})); return 1; }})()""")


async def tick(p, label):
    await p.eval(f"""[...document.querySelectorAll('label.chip')].find(l => l.textContent.includes({json.dumps(label)}))
      .querySelector('input').click(); 1""")
    await asyncio.sleep(0.2)


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.eval(f"window.__rlEmulatorSignIn({json.dumps(EMAIL)}, 'Onboarding Check')")
        await asyncio.sleep(4)
        print("[signed in] path", await p.eval("location.pathname"))
        await check(p, "screen1", "#welcome-title")

        # --- the timed flow (light, 1440)
        await p.viewport(1440)
        await theme(p, False)
        await p.goto(W + "/welcome", wait=1)
        await p.wait_for("#welcome-title")
        t0 = time.monotonic()
        await tick(p, "Software")
        await tick(p, "Watch")  # decision 68: read / watch / listen
        await tick(p, "Economics")
        await tick(p, "Sports")
        await type_text(p, ".freetext__input", "F1, startups, mergers and acquisitions")
        await p.eval("document.querySelector('.consent__check input').click(); 1")
        await p.click_text("button", "Continue", 1)
        await p.wait_for(".matches", 40)
        await asyncio.sleep(1)
        print("[matches]", await p.eval("document.querySelector('.matches').innerText.replace(/\\n+/g, ' | ')"))
        print("[screen1 matches]", await p.shot("screen1-matches-1440-light", full=True))
        await p.click_text("button", "Continue", 1)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 60)
        t_cards = time.monotonic() - t0
        await asyncio.sleep(2)
        cards = await p.eval("document.querySelectorAll('.discover-card').length")
        topics = await p.eval("[...document.querySelectorAll('.discover-card__topic')].map(e => e.textContent)")
        print(f"[screen2] cards={cards} after {t_cards:.1f}s topics={topics}")
        await check(p, "screen2", ".discover-card:not(.discover-card--ghost)")

        # --- keyboard (acceptance 6): Tab to the first card's buttons, answer with Space and Enter
        await p.viewport(1440)
        await theme(p, False)
        await p.goto(W + "/welcome", wait=1)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 40)
        await asyncio.sleep(1)
        kb = {"pick_focus": await tab_to(p, ".discover-card__answers .answer")}
        await press(p, " ")
        await asyncio.sleep(0.5)
        kb["space_picks"] = await p.eval("document.querySelector('.discover-card__answers .answer').getAttribute('aria-pressed')")
        kb["focus_kept_after_answer"] = await p.eval("document.activeElement?.matches('.discover-card__answers .answer')")
        # decision 68 K4b: the Quick check below the cards, all terms at once
        kb["quick_focus"] = await tab_to(p, ".quickcheck__answers .answer")
        await press(p, "Enter")
        await asyncio.sleep(1.5)
        kb["quick_answer_pressed"] = await p.eval(
            "document.querySelector('.quickcheck__answers .answer[aria-pressed=true]') !== null")
        kb["quick_focus_kept"] = await p.eval("document.activeElement?.matches('.quickcheck__answers .answer') ?? false")
        kb["quick_rows"] = await p.eval("document.querySelectorAll('.quickcheck__row').length")
        kb["start_focus"] = await tab_to(p, ".welcome__actions .btn--primary", 120)
        print("[keyboard screen2]", kb)

        # --- answers: two Not for me on Sports, like the rest; then one quick check answer and skip
        await p.viewport(1440)
        await theme(p, False)
        await p.goto(W + "/welcome", wait=1)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 40)
        await asyncio.sleep(1)
        done = await p.eval("""(async () => { const out = []; let sports = 0;
          for (const card of document.querySelectorAll('.discover-card')) {
            const topic = card.querySelector('.discover-card__topic').textContent;
            const like = [...card.querySelectorAll('button')].find(b => b.textContent.startsWith("I'd"))?.textContent;
            const want = topic === 'Sports' && sports < 2 ? 'Not for me' : like;
            if (want === 'Not for me') sports += 1;
            [...card.querySelectorAll('button')].find(b => b.textContent === want)?.click();
            out.push(topic + ':' + want); await new Promise(r => setTimeout(r, 300)); }
          const rows = [...document.querySelectorAll('.quickcheck__row')];
          for (const [i, label] of [[rows.length - 1, 'New to me'], [1, 'Heard of it']]) {  // out of order
            [...rows[i].querySelectorAll('button')].find(b => b.textContent === label)?.click();
            await new Promise(r => setTimeout(r, 800)); }
          out.push('quick answered:' + document.querySelectorAll('.quickcheck__answers .answer[aria-pressed=true]').length);
          [...document.querySelectorAll('button')].find(b => b.textContent === 'Skip quick check')?.click();
          out.push('formats:' + [...document.querySelectorAll('.discover-card__meta')].map(m => m.textContent.split(' · ').pop()).join('/'));
          return out; })()""")
        await asyncio.sleep(2)
        print("[answers]", done)
        print("[readback]", await p.eval("document.querySelector('.welcome__says').textContent"))
        print("[screen2 readback]", await p.shot("screen2-readback-1440-light", full=True))
        await p.viewport(390)
        print("[screen2 readback 390]", await p.shot("screen2-readback-390-light", full=True))
        await p.viewport(1440)
        await p.click_text("button", "Start reading", 3)
        t_feed = time.monotonic() - t0
        print(f"[feed] path={await p.eval('location.pathname')} total {t_feed:.1f}s (scripted)")
        feed = (await p.api("", "GET", "/v1/feed"))["body"]
        print("[feed topics]", feed["topics"])
        prof = (await p.api("", "GET", "/v1/me/profile"))["body"]
        print("[profile]", {d["domain"]: (round(d["theta"], 3), d["interest"]) for d in prof["domains"]
                            if d["interest"] >= 0.5 or abs(d["theta"]) > 1e-6})
        await asyncio.sleep(2)
        print("[feed shot]", await p.shot("feed-after-onboarding-1440-light"))
        print("[delete]", (await p.api("", "DELETE", "/v1/me"))["status"])
    finally:
        await ws.close()
        cdp.stop()


if __name__ == "__main__":
    asyncio.run(main())
