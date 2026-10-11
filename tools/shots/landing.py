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

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4173"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))
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


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await cdp.Page.reset_auth(p, BASE)
        report = {"demo": await demo_checks(p)}

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
        print(json.dumps(report, indent=2))
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
