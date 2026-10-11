"""Decision 50 on the local harness: an Indian reader's For you from top outlets (60/40),
Refresh at no search cost, Redo setup updating For you without a reload, the country field.
Emulators only (`make dev-emulator`, then `scripts.collect_outlets` into the emulator). No LLM
call here: articles are opened with phase 1 only (fetch + extract), which has none.

    SHOTS_OUT=docs/evidence/d50 uv run --project apps/api python tools/shots/d50.py
"""

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import urlsplit

sys.path.insert(0, __file__.rsplit("/", 1)[0])
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "apps" / "api"))
import cdp  # noqa: E402
from onboarding import theme, tick  # noqa: E402

from app.recs.outlets import side_of  # noqa: E402

W = "http://localhost:5173"
EMULATOR = "http://127.0.0.1:8085/v1/projects/demo-readlayer/databases/(default)/documents"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))
results: dict[str, object] = {}


def search_calls() -> int:
    day = datetime.now(UTC).date().isoformat()
    try:
        with urllib.request.urlopen(f"{EMULATOR}/ops/search/days/{day}", timeout=5) as r:
            doc = json.load(r)
    except urllib.error.HTTPError:
        return 0
    return int(doc.get("fields", {}).get("calls", {}).get("integerValue", 0))


async def audit(p, name):
    a = await p.audit()
    tag = await p.eval("innerWidth + '-' + (localStorage.getItem('readlayer:theme') || 'light')")
    results[f"axe {name} {tag}"] = a["axe"]
    print(f"[{name} {tag}] axe={a['axe']} hscroll={a['hscroll']} small={json.dumps(a['small'])[:160]}",
          await p.shot(f"{name}-{tag}", full=True))


async def at_sizes(p, name, path, ready):
    for w, dark in SIZES:
        await p.viewport(w, dark=dark)
        await theme(p, dark)
        await p.goto(W + path, wait=2)
        await p.wait_for(ready, 40)
        await asyncio.sleep(1)
        await audit(p, name)
    await p.viewport(1440)
    await theme(p, False)


def mix(feed):
    arts = [i for i in feed["items"] if i["format"] == "article"]
    sides = [side_of(urlsplit(a["url"]).hostname or "", "IN") for a in arts]
    return arts, sides


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        ua = (await p.send("Browser.getVersion"))["userAgent"]
        await p.send("Emulation.setUserAgentOverride", userAgent=ua, acceptLanguage="en-IN")
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        print("[locale]", await p.eval("navigator.language"))
        email = f"d50-{int(time.time())}@example.com"  # a fresh emulator reader per run
        await p.eval(f"window.__rlEmulatorSignIn('{email}', 'D50 Check')")
        await asyncio.sleep(4)

        # --- screen 1: the country is prefilled from the locale, nothing stored before Continue
        await at_sizes(p, "screen1-country", "/welcome", "#welcome-title")
        await p.goto(W + "/welcome", wait=2)
        await p.wait_for("#welcome-title", 20)
        india = await p.eval("""[...document.querySelectorAll('label.chip')].find(l => l.textContent.includes('India'))
          .querySelector('input').checked""")
        results["prefilled India"] = india
        print("[prefill] India checked:", india)
        for label in ("Software", "Economics", "Politics", "Sports"):
            await tick(p, label)
        await p.eval("document.querySelector('.consent__check input').click(); 1")
        await p.click_text("button", "Continue", 2)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 60)
        profile = (await p.api("", "GET", "/v1/me/profile"))["body"]
        results["country stored"] = profile["settings"]["country"]
        discover = await p.eval("[...document.querySelectorAll('.discover-card a[href]')].map(a => a.href)")
        print("[screen 2] country", profile["settings"]["country"], "| card hosts",
              sorted({urlsplit(u).hostname for u in discover}))
        await p.click_text("button", "Start reading", 3)

        # --- For you: registry outlets, 60/40
        await p.wait_for(".feedtab .rows li", 40)
        feed = (await p.api("", "GET", "/v1/feed"))["body"]
        arts, sides = mix(feed)
        registry = sum(s is not None for s in sides)
        results["for you"] = {"topics": feed["topics"], "articles": len(arts), "registry": registry,
                              "local": sides.count("local"), "global": sides.count("global")}
        print("[for you]", results["for you"])
        for a, s in zip(arts, sides, strict=True):
            print(f"    {s or 'OTHER':6} {a['source']:14} {a['title'][:70]}")
        await at_sizes(p, "foryou", "/", ".feedtab .rows li")

        # --- 6 articles open fully (phase 1 only: fetch + extract, no LLM)
        opened = []
        for a in arts[:6]:
            r = await p.api("", "POST", "/v1/recs/open", {"url": a["url"]})
            cid = (r["body"] or {}).get("content_id")
            words = 0
            if cid:
                doc = (await p.api("", "GET", f"/v1/content/{cid}"))["body"] or {}
                words = sum(len(str(x.get("text", "")).split()) for x in doc.get("paragraphs", []))
            opened.append((a["source"], r["status"], words))
        results["opened"] = opened
        print("[opened]", opened)

        # --- Refresh: no search, no reload
        await p.goto(W + "/", wait=2)
        await p.wait_for(".feedtab .rows li", 40)
        await p.eval("window.__d50 = 1; performance.clearResourceTimings(); 1")
        before = search_calls()
        await p.click_text(".feedtab__refresh", "Refresh", 3)
        fetched = await p.eval("performance.getEntriesByType('resource').filter(e => e.name.includes('/v1/feed')).length")
        results["refresh"] = {"feed_requests": fetched, "searches_added": search_calls() - before,
                              "same_page": await p.eval("window.__d50 === 1")}
        print("[refresh]", results["refresh"])

        # --- Redo setup adds Health; For you updates without a page reload
        await p.goto(W + "/profile", wait=2)
        await p.wait_for(".data__redo button", 20)
        await p.eval("window.__d50 = 2; 1")
        await p.click_text(".data__redo button", "Redo setup", 3)
        await p.wait_for("#welcome-title", 20)
        await tick(p, "Health")
        if await p.eval("!!document.querySelector('.consent__check input')"):
            await p.eval("document.querySelector('.consent__check input').click(); 1")
        await p.click_text("button", "Continue", 2)
        await p.wait_for(".discover-card:not(.discover-card--ghost)", 60)
        await p.click_text("button", "Start reading", 3)
        await p.wait_for(".feedtab .rows li", 40)
        await asyncio.sleep(2)
        rows = await p.eval("[...document.querySelectorAll('.feedtab .rows li')].map(li => li.textContent)")
        results["redo"] = {"same_page": await p.eval("window.__d50 === 2"),
                           "health_rows": sum("in Health" in r for r in rows),
                           "topics": (await p.api("", "GET", "/v1/feed"))["body"]["topics"]}
        print("[redo]", results["redo"])

        # --- Preferences: the country field
        await at_sizes(p, "prefs-country", "/profile#prefs-title", "#prefs-title")

        print("[delete]", (await p.api("", "DELETE", "/v1/me"))["status"])
        print("\nRESULTS", json.dumps(results, default=str))
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
