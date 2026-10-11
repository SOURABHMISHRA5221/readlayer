"""Decision 48 on the local harness: topic goal, set_interest edit, Redo setup for an M7-era
reader (consent v1, comfort answers, finished). Emulators only; real model calls are a handful.

    SHOTS_OUT=docs/evidence/d48 uv run --project apps/api python tools/shots/d48.py
"""

import asyncio
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
from onboarding import theme, tick  # noqa: E402

W = "http://localhost:5173"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))


async def audit(p, name):
    a = await p.audit()
    tag = await p.eval("innerWidth + '-' + (localStorage.getItem('readlayer:theme') || 'light')")
    print(f"[{name} {tag}] axe={a['axe']} hscroll={a['hscroll']} small={json.dumps(a['small'])[:160]}",
          await p.shot(f"{name}-{tag}", full=True))


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        email = f"d48-{int(time.time())}@example.com"  # a fresh emulator reader per run
        await p.eval(f"window.__rlEmulatorSignIn('{email}', 'D48 Check')")
        await asyncio.sleep(4)
        # An M7-era reader: consent v1, the old onboarding answers, finished.
        print("[setup]", (await p.api("", "POST", "/v1/me/consent", {"version": "consent-v1"}))["status"],
              (await p.api("", "POST", "/v1/onboarding", {"field": "software", "interests": ["economics"],
               "comfort": {"economics": "comfortable"}, "thinks_in": ["cricket"]}))["status"],
              (await p.api("", "POST", "/v1/calibration/skip", {}))["status"])

        # --- topic goal: preview, then save
        await p.goto(W + "/profile", wait=2)
        await p.wait_for(".goals__text", 20)
        await p.eval("""(() => { const el = document.querySelector('.goals__text');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, 'Indian politics');
          el.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()""")
        # The idea form is the one holding .goals__text (the first "Add" belongs to the habit form).
        await p.eval("document.querySelector('.goals__text').form.requestSubmit(); 1")
        await p.wait_for(".goals__draft", 40)
        print("[goal preview]", await p.eval("document.querySelector('.goals__draft-line').textContent"))
        # Profile with the draft line and the Redo button, all four sizes, without a reload (a
        # reload would drop the draft): viewport and the theme attribute change in place.
        print("[redo button shown]", await p.eval("!!document.querySelector('.data__redo button')"))
        for w, dark in SIZES:
            await p.viewport(w, dark=dark)
            await p.eval(f"document.documentElement.dataset.theme = '{'dark' if dark else 'light'}'; "
                         f"localStorage.setItem('readlayer:theme', '{'dark' if dark else 'light'}'); 1")
            await asyncio.sleep(0.8)
            await audit(p, "profile-goal-draft")
        await p.viewport(1440)
        await p.eval("document.documentElement.dataset.theme = 'light'; localStorage.setItem('readlayer:theme', 'light'); 1")
        await p.click_text(".goals__draft button", "Save goal", 2)
        goals = (await p.api("", "GET", "/v1/me/goals"))["body"]
        print("[goal saved]", [(g["label"], g.get("kind"), g["total"]) for g in goals])

        # --- Describe yourself: set_interest, Apply, Undo
        await p.eval("""(() => { const el = document.querySelector('.editbox textarea');
          Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, 'See I want to learn about Indian Politics');
          el.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()""")
        await p.click_text(".editbox button", "Preview changes", 1)
        await p.wait_for(".editbox__preview", 40)
        print("[edit preview]", await p.eval("document.querySelector('.editbox__preview').innerText.replace(/\\n+/g, ' | ')"))
        before = (await p.api("", "GET", "/v1/me/profile"))["body"]
        pol = lambda prof: next(d["interest"] for d in prof["domains"] if d["domain"] == "politics")  # noqa: E731
        await p.click_text(".editbox__preview button", "Apply", 2)
        after = (await p.api("", "GET", "/v1/me/profile"))["body"]
        feed = (await p.api("", "GET", "/v1/feed"))["body"]
        print(f"[edit apply] politics interest {pol(before)} → {pol(after)}; feed topics {feed['topics']}")
        await audit(p, "profile-after-edit")
        await p.click_text("button", "Undo", 2)
        print("[edit history]", await p.eval("document.querySelector('.editbox__history li span')?.textContent"))
        print("[edit undo] politics interest", pol((await p.api("", "GET", "/v1/me/profile"))["body"]))

        # --- Redo setup through the real button
        await p.goto(W + "/profile", wait=2)
        await p.wait_for(".data__redo button", 20)
        await p.click_text(".data__redo button", "Redo setup", 3)
        print("[redo] path", await p.eval("location.pathname"),
              "| consent shown", await p.eval("!!document.querySelector('.consent__check')"),
              "| cancel shown", await p.eval("[...document.querySelectorAll('button')].some(b => b.textContent === 'Cancel setup')"))
        for w, dark in SIZES:
            await p.viewport(w, dark=dark)
            await theme(p, dark)
            await p.goto(W + "/welcome", wait=2)
            await p.wait_for("#welcome-title", 20)
            await asyncio.sleep(1)
            await audit(p, "redo-screen1")
        await p.viewport(1440)
        await theme(p, False)
        await p.goto(W + "/welcome", wait=2)
        await p.wait_for("#welcome-title", 20)
        await tick(p, "Politics")
        await tick(p, "Sports")
        await p.eval("document.querySelector('.consent__check input').click(); 1")
        await p.click_text("button", "Continue", 2)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 60)
        await asyncio.sleep(1.5)
        for w, dark in SIZES:
            await p.viewport(w, dark=dark)
            await theme(p, dark)
            await p.goto(W + "/welcome", wait=2)
            await p.wait_for(".discover-card:not(.discover-card--ghost)", 40)
            await asyncio.sleep(1)
            await audit(p, "redo-screen2")
        await p.viewport(1440)
        await theme(p, False)
        await p.goto(W + "/welcome", wait=2)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 40)
        await p.click_text("button", "Start reading", 3)
        prof = (await p.api("", "GET", "/v1/me/profile"))["body"]
        user = prof["onboarding"]
        print("[redo done] path", await p.eval("location.pathname"), "| onboarding", user,
              "| thinks_in", prof["thinks_in"],
              "| feed topics", (await p.api("", "GET", "/v1/feed"))["body"]["topics"])
        exported = (await p.api("", "GET", "/v1/me/export"))["body"]
        print("[comfort kept]", exported["user"]["onboarding"]["comfort"],
              "| typed text stored anywhere:", "Indian" in json.dumps(exported))
        print("[delete]", (await p.api("", "DELETE", "/v1/me"))["status"])
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
