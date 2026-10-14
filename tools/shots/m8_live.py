"""M8 live check (docs/plans/M8.md "Production data writes"): the production-built Gloss extension
against the live API and web app, one demo reader, one page not yet in the library.

    pnpm --filter extension build
    SHOTS_OUT=docs/evidence/m8/live uv run --project apps/api python tools/shots/m8_live.py [url name]

Writes in production: one anonymous test reader (deleted at the end), 1 `contents/` doc under the
page's `ext:` id (kept; only its submitter could read it), +1 shared anonymous ingest counter,
≤ 5 `graph_growth/` docs, ≈ $0.01 LLM. Also forces one token refresh (securetoken), which the
emulator harness never exercises.
"""

import asyncio
import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import m8  # noqa: E402

from live_site import WEB as LIVE_WEB  # noqa: E402
LIVE_API = "https://readlayer-api-d2sfihz3za-el.a.run.app"
# Default: the plan's page. It redirects to Wikipedia's "Yield curve", already a corpus doc, so
# that run reuses the fetch doc; pass a page that is really new to exercise a new `ext:` ingest.
PAGE = sys.argv[1] if len(sys.argv) > 1 else "https://en.wikipedia.org/wiki/Term_structure_of_interest_rates"
NAME = sys.argv[2] if len(sys.argv) > 2 else "wikipedia"


async def main() -> None:
    m8.W, m8.API, m8.RULES = LIVE_WEB, LIVE_API, "MAP nothing.invalid 127.0.0.1"
    m8.launch()
    version = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{m8.PORT}/json/version").read())
    browser = await m8.attach(version["webSocketDebuggerUrl"])
    created = (await browser.send("Target.createTarget", url="about:blank"))["targetId"]
    await asyncio.sleep(1)
    page = await m8.attach(next(t for t in m8.targets() if t["id"] == created)["webSocketDebuggerUrl"])
    await page.send("Page.enable")
    await page.send("Runtime.enable")
    sw = None
    for _ in range(40):
        sw = next((t for t in m8.targets() if t["url"].startswith(f"chrome-extension://{m8.EXT_ID}/")
                   and t["type"] == "service_worker"), None)
        if sw:
            break
        await asyncio.sleep(0.25)
    worker = await m8.attach(sw["webSocketDebuggerUrl"])
    await worker.send("Runtime.enable")
    await worker.send("Network.enable")
    h = m8.Harness(browser, page, created, worker)
    try:
        await m8.demo_sign_in(h)
        m8.record("live connect", await m8.connect(h))
        mark = len(worker.events)
        got = await h.read_site("live-demo", NAME, PAGE, negative=True)
        cid = h.content_id(mark)
        got["content_id"] = cid
        m8.record("live read", got)
        hosts = sorted({e["params"]["request"]["url"].split("/")[2] for e in worker.events
                        if e["method"] == "Network.requestWillBeSent"})
        m8.record("worker talked to", hosts)

        # Force one token refresh: expire the stored token, then read again (the reader's own
        # doc is reused: no new ingest), and look for the securetoken call.
        await worker.eval("chrome.storage.session.get('session').then(({session}) => "
                          "chrome.storage.session.set({session: {...session, expiresAt: 0}})).then(() => 1)")
        mark = len(worker.events)
        await h.goto(PAGE, wait=5)
        popup = await h.press_read()
        notes = await h.wait_notes()
        refresh = [e["params"]["request"]["url"].split("?")[0] for e in worker.events[mark:]
                   if e["method"] == "Network.requestWillBeSent" and "securetoken" in e["params"]["request"]["url"]]
        statuses = [e["params"]["response"]["status"] for e in worker.events[mark:]
                    if e["method"] == "Network.responseReceived" and "securetoken" in e["params"]["response"]["url"]]
        m8.record("after forced refresh", {"popup": popup, "notes": notes, "securetoken_calls": refresh,
                                           "securetoken_status": statuses, "same_doc": h.content_id(mark) == cid,
                                           "counts": await h.p.eval(m8.COUNTS_JS)})

        # The page is in this reader's library; then the test reader is deleted. (That another
        # reader gets 404 is covered on the emulator, STATUS §22: the plan lists one live reader.)
        await h.goto(LIVE_WEB + "/", wait=4)
        library = (await h.p.api(LIVE_API, "GET", "/v1/content?density=balanced"))["body"] or []
        m8.record("in the reader's library", cid in {r["id"] for r in library})
        m8.record("delete test reader", (await h.p.api(LIVE_API, "DELETE", "/v1/me"))["status"])
    finally:
        import os
        import subprocess
        from pathlib import Path
        out = Path(os.environ.get("SHOTS_OUT", "/tmp/gloss-shots")) / f"m8-live-results-{NAME}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(m8.results, indent=2, default=str))
        print("[results]", out)
        subprocess.run(["pkill", "-f", f"remote-debugging-port={m8.PORT}"], check=False)


if __name__ == "__main__":
    asyncio.run(main())
