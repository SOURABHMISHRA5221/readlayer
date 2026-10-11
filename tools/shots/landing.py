"""Landing checks (Landing and onboarding, plan A): screenshots, the demo toggle, no network
after load, axe at every impact level, the first-paint boot switch and signed-out deep links.

    pnpm --filter web build && pnpm --filter web preview   # http://127.0.0.1:4173
    uv run --project apps/api python tools/shots/landing.py [base]

Signed out throughout: no account is created and nothing is written anywhere.
"""

import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402
import landing_d46  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4173"
SIZES = ((1920, False), (1440, False), (1440, True), (1280, False), (1280, True), (390, False), (390, True))
# Dark is only ever the reader's toggle (decision 44), so shots set it the way the toggle does.
THEME = "localStorage.setItem('readlayer:theme', '{}'); true"
AXE_ALL = "axe.run(document, {resultTypes: ['violations']}).then(r => r.violations.map(v => v.impact + ' ' + v.id + ':' + v.nodes.length))"
# Counts every request the page makes from here on: resource timing plus fetch/XHR calls.
NET_START = """(() => { window.__rlNet = {fetch: 0, xhr: 0, base: performance.getEntriesByType('resource').length};
  const f = window.fetch; window.fetch = (...a) => { window.__rlNet.fetch++; return f(...a); };
  const o = XMLHttpRequest.prototype.open; XMLHttpRequest.prototype.open = function (...a) { window.__rlNet.xhr++; return o.apply(this, a); };
  return true; })()"""
NET_END = """(() => ({fetch: window.__rlNet.fetch, xhr: window.__rlNet.xhr,
  resources: performance.getEntriesByType('resource').slice(window.__rlNet.base).map(e => e.name)}))()"""
MARKS = "[...document.querySelectorAll('.lp-demo .rl-mark')].map(m => m.textContent + ' [' + [...m.classList].filter(c => c.startsWith('rl-mark--')).join(' ') + ']')"
CARD = "(() => { const c = document.querySelector('.rl-card'); return c ? c.innerText.replace(/\\s+/g, ' ').slice(0, 420) : null; })()"


async def demo_checks(p):
    await p.viewport(1440)
    await p.goto(BASE + "/", wait=1)
    assert await p.wait_for(".lp-demo .rl-mark"), "demo marks never appeared"
    await asyncio.sleep(1.5)  # fonts and the card faces finish loading before the window starts
    await p.eval(NET_START)
    out = {}
    for label in ("Cricket fan", "Policy student", "Software engineer"):
        await p.click_text(".lp-demo [role=radio]", label, 1.2)
        marks = await p.eval(MARKS)
        await p.eval("document.querySelector('.lp-demo .rl-mark').click(); true")
        await asyncio.sleep(0.8)
        card = await p.eval(CARD)
        await p.eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); true")
        await asyncio.sleep(0.4)
        out[label] = {"marks": marks, "card": card}
    out["network_after_load"] = await p.eval(NET_END)
    return out


KEYS = {"Tab": 9, "Enter": 13, "Escape": 27, "ArrowRight": 39, " ": 32}


async def press(p, key, shift=False):
    code = "Space" if key == " " else key
    # Enter and Space carry text, as a real keyboard's keydown does (Enter clicks a button).
    text = {"Enter": "\r", " ": " "}.get(key)
    for kind in ("keyDown" if text else "rawKeyDown", "keyUp"):
        extra = {"text": text} if text and kind == "keyDown" else {}
        await p.send("Input.dispatchKeyEvent", type=kind, key=key, code=code, modifiers=8 if shift else 0,
                     windowsVirtualKeyCode=KEYS[key], nativeVirtualKeyCode=KEYS[key], **extra)
    await asyncio.sleep(0.15)


async def tab_to(p, selector, limit=60):
    for _ in range(limit):
        await press(p, "Tab")
        if await p.eval(f"!!document.activeElement?.matches({json.dumps(selector)})"):
            return True
    return False


async def keyboard_checks(p):
    """Acceptance 6: the demo toggle, a highlight and its card by keyboard alone."""
    await p.viewport(1440)
    await p.goto(BASE + "/", wait=2)
    checked = "document.querySelector('.lp-demo [role=radio][aria-checked=true]')?.textContent.trim()"
    out = {"toggle_focus": await tab_to(p, ".lp-demo [role=radio]")}
    before = await p.eval(checked)
    await press(p, "ArrowRight")
    out["arrow_changes_persona"] = f"{before} → {await p.eval(checked)}"
    out["mark_focus"] = await tab_to(p, ".lp-demo .rl-mark")
    mark = await p.eval("document.activeElement.textContent.trim()")
    await press(p, "Enter")
    await asyncio.sleep(0.8)
    # The demo always shows one open note (decision 46); Enter swaps it to the focused mark's.
    title = await p.eval("document.querySelector('.lp-demo__note-live .rl-card__title')?.textContent ?? ''")
    out["enter_shows_its_note"] = f"{mark} → {title}"
    out["mark_expanded"] = await p.eval("document.activeElement?.getAttribute('aria-expanded') === 'true'"
                                        " && !!document.getElementById(document.activeElement.getAttribute('aria-controls'))")
    await press(p, "Escape")
    await asyncio.sleep(0.5)
    out["focus_stays_on_mark"] = await p.eval("!!document.activeElement?.matches('.lp-demo .rl-mark')")
    out["pass"] = (out["toggle_focus"] and before != out["arrow_changes_persona"].split(" → ")[1]
                   and out["mark_focus"] and out["mark_expanded"]
                   and out["focus_stays_on_mark"])
    return out


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await cdp.Page.reset_auth(p, BASE)
        report = {"demo": await demo_checks(p)}
        net = report["demo"]["network_after_load"]
        assert net["fetch"] == 0 and net["xhr"] == 0 and not net["resources"], f"network after load: {net}"

        for w, dark in SIZES:
            await p.viewport(w, dark=dark)
            await p.eval(THEME.format("dark" if dark else "light"))
            await p.goto(BASE + "/", wait=2.5)
            name = f"landing-{w}-{'dark' if dark else 'light'}"
            await p.eval(cdp.AXE.read_text() + ";'axe'")
            report[name] = {
                "shot": await p.shot(name, full=True),
                "fold": await p.shot(name + "-fold"),
                "axe": await p.eval(AXE_ALL),
                "hscroll": await p.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth"),
                "small": await p.eval(cdp.SMALL_JS),
            }
            await p.eval("document.querySelector('.lp-demo .rl-mark').click(); true")
            await asyncio.sleep(0.8)
            report[name]["card"] = await p.shot(name + "-card")
            report[name]["axe_card"] = await p.eval(AXE_ALL)

        for w, dark in SIZES:
            await p.viewport(w, dark=dark)
            await p.eval(THEME.format("dark" if dark else "light"))
            await p.goto(BASE + "/privacy", wait=2)
            name = f"privacy-{w}-{'dark' if dark else 'light'}"
            await p.eval(cdp.AXE.read_text() + ";'axe'")
            report[name] = {"shot": await p.shot(name, full=True), "axe": await p.eval(AXE_ALL),
                            "hscroll": await p.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth")}

        # Budgets (decision 44 V6): first view at 390×844 under ~1.5 MB, and no landing media
        # (shots, clips, posters, illustrations) requested before the reader scrolls.
        await p.viewport(390, 844)
        await p.eval(THEME.format("light"))
        await p.send("Network.enable")
        await p.send("Network.setCacheDisabled", cacheDisabled=True)
        await p.goto(BASE + "/", wait=4)
        report["first_view"] = await p.eval("""(() => { const r = performance.getEntriesByType('resource');
          const nav = performance.getEntriesByType('navigation')[0];
          return {bytes: r.reduce((n, e) => n + (e.transferSize || e.encodedBodySize || 0), 0) + (nav ? nav.transferSize : 0),
                  media_before_scroll: r.map(e => e.name).filter(n => n.includes('/landing/'))}; })()""")
        await p.send("Network.setCacheDisabled", cacheDisabled=False)

        # First paint: what theme-init.js chose, per path and hint.
        await p.viewport(1440)
        boot = {}
        for path, hint in (("/", False), ("/", True), ("/privacy", False), ("/read/abc", False)):
            await p.eval(f"localStorage.{'setItem' if hint else 'removeItem'}('readlayer:signed-in', '1'); true")
            await p.goto(BASE + path, wait=0.05)
            boot[f"{path} hint={hint}"] = await p.eval("document.documentElement.dataset.boot")
        await p.eval("localStorage.removeItem('readlayer:signed-in'); true")
        report["boot"] = boot

        # A signed-out deep link: the landing, a notice, and the path kept for after sign-in.
        await p.goto(BASE + "/read/abc?persona=trader", wait=2.5)
        report["deep_link"] = {
            "notice": await p.eval("document.querySelector('.lp-notice')?.textContent ?? null"),
            "return_to": await p.eval("sessionStorage.getItem('readlayer:return-to')"),
            "url": await p.eval("location.pathname + location.search"),
        }
        await p.eval(THEME.format("light"))
        report["d46"] = await landing_d46.run_all(p, BASE)
        # Last: it switches the persona and closes the open note, which the checks above assume.
        await cdp.Page.reset_auth(p, BASE)
        report["keyboard"] = await keyboard_checks(p)
        print(json.dumps(report, indent=2))
        failed = [k for k, v in report["d46"].items() if not v["pass"] and k not in landing_d46.KNOWN]
        known = {k: v for k, v in report["d46"].items() if not v["pass"] and k in landing_d46.KNOWN}
        print("decision 46 known shortfalls (reported to Sourabh):", json.dumps(known))
        print("decision 46 checks:", "all pass" if not failed else f"FAIL {failed}")
        axe = {k: v[key] for k, v in report.items() if isinstance(v, dict)
               for key in ("axe", "axe_card") if v.get(key)}
        print("axe (every impact level):", "0 everywhere" if not axe else f"FAIL {axe}")
        print("keyboard:", json.dumps(report["keyboard"]))
        if failed or axe or not report["keyboard"]["pass"]:
            raise SystemExit(1)
    finally:
        await ws.close()
        cdp.stop()


if __name__ == "__main__":
    asyncio.run(main())
