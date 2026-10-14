"""Readiness on For you (decision 60, docs/plans/readiness.md acceptance 2): the demo reader's
For you, ranked by the local API from a committed newcomer feed written into the emulator. At
1440 and 390, light and dark: axe at every impact, horizontal scroll, and that every row whose
item names an idea on the map has a readiness line (rows naming none have none). Asserts zero
search and zero model calls. Emulators only (`make dev-emulator`).

    SHOTS_OUT=docs/evidence/readiness uv run --project apps/api python tools/shots/readiness.py

Exits non-zero on any failed check.
"""

import asyncio
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp

W = "http://localhost:5173"
EMULATOR = "http://127.0.0.1:8085/v1/projects/demo-readlayer/databases/(default)/documents"
OWNER = {"Authorization": "Bearer owner"}
SIZES = ((1440, False), (1440, True), (390, False), (390, True))
FIXTURE = Path(__file__).parent / "fixtures" / "readiness_feed.json"
LINES = {"Mostly familiar": "familiar", "Ready for you": "ready"}

AXE_ALL = ("axe.run(document, {resultTypes: ['violations']}).then(r => r.violations"
           ".map(v => v.impact + ':' + v.id + ':' + v.nodes.length))")
ROWS_JS = """(() => [...document.querySelectorAll('article.row')].map((r) => ({
  title: (() => { const t = r.querySelector('.row__title')?.cloneNode(true); if (!t) return null;
    t.querySelectorAll('.visually-hidden').forEach((e) => e.remove()); return t.textContent.trim(); })(),
  line: r.querySelector('.row__why [title]')?.textContent || null,
  basis: r.querySelector('.row__why [title]')?.getAttribute('title') || null,
  meta: r.querySelector('.row__meta')?.textContent || '' })))()"""

failures: list[str] = []
out: dict = {}


def check(ok: bool, what: str) -> None:
    if not ok:
        failures.append(what)
        print(f"  FAIL {what}", flush=True)


def emulator(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{EMULATOR}/{path}", data, {**OWNER, "Content-Type": "application/json"},
                                 method=method)  # fmt: skip
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise


def counters() -> dict[str, str]:
    """Today's search-provider calls and LLM calls in the emulator's ledgers."""
    day = datetime.now(UTC).date().isoformat()
    calls = {}
    for name in ("search", "spend"):
        fields = emulator("GET", f"ops/{name}/days/{day}").get("fields", {})
        calls[name] = fields.get("calls", {}).get("integerValue", "0")
    return calls


def level(line: str | None) -> str | None:
    if line is None:
        return None
    return LINES.get(line, "stretch" if line.startswith("A stretch: ") else f"unknown: {line}")


async def main() -> None:
    emulator("PATCH", "persona_feeds/newcomer", json.loads(FIXTURE.read_text()))
    before = counters()
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.viewport(1440)
        await p.reset_auth(W)
        await p.goto(W + "/", wait=3)
        await p.wait_for(".lp-nav__cta", 20)
        await p.eval("document.querySelector('.lp-nav__cta').click(); 1")
        await asyncio.sleep(4)
        feed = await p.api(W, "GET", "/v1/feed?persona=newcomer")
        check(feed["status"] == 200, f"/v1/feed status {feed['status']}")
        api = {i["title"]: i for i in feed["body"]["items"]}
        out["api"] = {
            "rows": len(api),
            "levels": dict(Counter(i.get("readiness") or "no line" for i in api.values())),
            "named_none": [t for t, i in api.items() if i.get("readiness") is None],
        }
        print(f"[api] {out['api']}", flush=True)
        for width, dark in SIZES:
            name = f"foryou-{width}-{'dark' if dark else 'light'}"
            await p.viewport(width, dark=dark)
            await p.eval(f"localStorage.setItem('readlayer:theme', '{'dark' if dark else 'light'}'); 1")
            await p.goto(f"{W}/for-you?persona=newcomer", wait=1.5)
            check(await p.wait_for("article.row", 30), f"{name}: no rows")
            await asyncio.sleep(1.5)
            rows = await p.eval(ROWS_JS)
            await p.eval(cdp.AXE.read_text() + ";'axe'")
            axe = await p.eval(AXE_ALL)
            hscroll = await p.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            shown = Counter(level(r["line"]) or "no line" for r in rows)
            out[name] = {"axe": axe, "hscroll": hscroll, "levels": dict(shown), "rows": rows}
            print(f"[{name}] axe={axe} hscroll={hscroll} levels={dict(shown)} {await p.shot(name, full=False)}",
                  flush=True)  # fmt: skip
            await p.shot(f"{name}-full", full=True)
            check(not axe, f"{name}: axe {axe}")
            check(hscroll == 0, f"{name}: horizontal scroll {hscroll}")
            check(len(rows) == len(api), f"{name}: {len(rows)} rows on screen, {len(api)} from the API")
            for r in rows:
                want = api.get(r["title"], {}).get("readiness")
                check(level(r["line"]) == want, f"{name}: {r['title']!r} shows {r['line']!r}, API says {want!r}")
                check(r["line"] is None or r["basis"] == "Based on the ideas named in the title and summary",
                      f"{name}: {r['title']!r} basis {r['basis']!r}")  # fmt: skip
                check(not any(w in r["meta"] for w in ("stretch", "Ready for", "familiar")),
                      f"{name}: readiness in the meta line of {r['title']!r}")  # fmt: skip
        out["levels_seen"] = sorted({lv for k, v in out.items() if k.startswith("foryou") for lv in v["levels"]})
        print(f"[levels on screen] {out['levels_seen']}", flush=True)
    finally:
        after = counters()
        out["calls"] = {"before": before, "after": after}
        print(f"[calls] search/model before {before} after {after}", flush=True)
        check(before == after, f"search or model calls during the run: {before} -> {after}")
        cdp.OUT.mkdir(parents=True, exist_ok=True)
        (cdp.OUT / "metrics.json").write_text(json.dumps(out, indent=1))
        await ws.close()
        cdp.stop()
    print(f"\n{len(failures)} failed checks" + ("" if not failures else ":\n" + "\n".join(failures)))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
