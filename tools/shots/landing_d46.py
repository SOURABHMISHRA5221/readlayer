"""Decision 46 checks for tools/shots/landing.py (plan P6 and round 1): first views, the open note,
no tracked caps, Margo and phone overlaps, the static → live swap, and clip legibility.

Each check returns its numbers and a pass flag; landing.py prints them and exits non-zero on a fail.
"""

import asyncio
import json
from pathlib import Path

PERSONAS = (("Software engineer", "Basis points"), ("Cricket fan", "Monetary tightening"), ("Policy student", "Basis points"))
CROPS = json.loads((Path(__file__).resolve().parent / "clip_crops.json").read_text())
CARD_TEXT_PX = 14  # the smallest card body size in the clips
# Measured shortfalls reported to Sourabh rather than forced (decision 46b round 1 items 2 and 3):
# printed with their numbers, not counted as failures.
# 390 clip text: ≈ 11px on phones from one natural-zoom recording; asked of Sourabh (46c/46d round 1
# item 1), listed here until he answers.
KNOWN = {"390 clip text"}

RECT = """(s => { const e = typeof s === 'string' ? document.querySelector(s) : s; if (!e) return null;
  const r = e.getBoundingClientRect(); return {t: r.top, b: r.bottom, l: r.left, r: r.right}; })"""
# Per-line rects of the visible text under a root (Range rects, so empty SVG area never counts).
TEXT_RECTS = """(sel => { const out = []; document.querySelectorAll(sel).forEach(root => {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) { if (!n.textContent.trim() || !n.parentElement.checkVisibility()) continue;
    const g = document.createRange(); g.selectNodeContents(n);
    for (const r of g.getClientRects()) if (r.width && r.height) out.push({t: r.top, b: r.bottom, l: r.left, r: r.right}); } });
  return out; })"""
CAPS = """(() => [...document.querySelectorAll('body *')].filter(e => e.checkVisibility() && e.textContent.trim()).map(e => {
  const c = getComputedStyle(e); const ls = parseFloat(c.letterSpacing) || 0;
  const bad = c.textTransform === 'uppercase' || /small-caps/.test(c.fontVariant + ' ' + c.fontVariantCaps) || ls / parseFloat(c.fontSize) > 0.02;
  return bad ? (e.className.baseVal ?? e.className) + ': ' + e.textContent.trim().slice(0, 30) : null; }).filter(Boolean))()"""
# Records the note slot's height on every frame from the first one (installed before the page loads).
SAMPLER = """window.__slot = []; (function tick() { const n = document.querySelector('.lp-demo__note');
  const s = document.querySelector('.lp-note-static');
  if (n) window.__slot.push([Math.round(n.getBoundingClientRect().height * 10) / 10, s ? !s.hidden : false]);
  if (window.__slot.length < 900) requestAnimationFrame(tick); })();"""


def hit(a, b):
    return a and b and a["l"] < b["r"] and b["l"] < a["r"] and a["t"] < b["b"] and b["t"] < a["b"]


def check(ok, **numbers):
    return {"pass": bool(ok), **numbers}


NOTE = """(() => { const R = s => { const e = document.querySelector(s); if (!e) return null;
  const r = e.getBoundingClientRect(); return {t: r.top, b: r.bottom}; };
  const body = document.querySelector('.lp-demo__note-live .rl-card__body');
  const says = document.querySelector('.lp-demo__note-live .rl-card__says .rl-card__text');
  const g = document.createRange(); g.selectNodeContents(says); const lines = g.getClientRects();
  return {title: R('.lp-hero__title'), sub: R('.lp-hero__sub'), ctas: R('.lp-hero__copy .lp-ctas') || R('.lp-ctas__row'),
    demo: R('.lp-demo'), sheet: R('.lp-demo__sheet'), copy_end: R('.lp-hero__copy .lp-readwith') || R('.lp-hero__copy .lp-ctas'),
    note_title: R('.lp-demo__note-live .rl-card__title'), says_label: R('.lp-demo__note-live .rl-card__says .rl-card__section-label'),
    card: R('.lp-demo__note-live .rl-card'), says_last: lines[lines.length - 1].bottom,
    scrolls: body.scrollHeight - body.clientHeight, values: R('.lp-values'),
    card_title: document.querySelector('.lp-demo__note-live .rl-card__title')?.textContent}; })()"""


async def first_views(p, base):
    out = {}
    for w, h in ((1440, 900), (1280, 800)):
        await p.viewport(w, h)
        await p.goto(base + "/", wait=2.5)
        for label, title in PERSONAS:
            await p.click_text(".segmented__option", label, wait=0.8)
            r = await p.eval(NOTE)
            # 46c: the whole hero in view for the first view's persona; after a switch, the note's
            # title and the author label (a taller note may run past the fold: user action).
            if label == "Software engineer":
                bottom = max(r[k]["b"] for k in ("title", "sub", "ctas", "demo", "copy_end"))
            else:
                bottom = max(r["note_title"]["b"], r["says_label"]["b"])
            out[f"{w}x{h} {label}"] = check(bottom <= h and r["card_title"] == title, bottom=round(bottom), note=r["card_title"])
            out[f"{w}x{h} {label} note in full"] = check(r["scrolls"] <= 1 and r["says_last"] <= r["card"]["b"],
                                                          inner_scroll=r["scrolls"])
            gap = round(r["sheet"]["b"] - r["copy_end"]["b"])
            if label == "Software engineer":
                out[f"{w}x{h} copy vs card (default)"] = check(abs(gap) <= 40, gap=gap)
            else:
                out[f"{w}x{h} copy vs card ({label}, info)"] = check(True, gap=gap)
    await p.viewport(390, 844)
    await p.goto(base + "/", wait=2.5)
    r = await p.eval(f"""(() => {{ const R = {RECT}; const t = document.querySelector('.lp-demo__note-live .rl-card__bg .rl-card__text');
      const g = document.createRange(); g.selectNodeContents(t); const first = g.getClientRects()[0];
      return {{title: R('.lp-hero__title'), ctas: R('.lp-ctas__row'), note_title: R('.lp-demo__note-live .rl-card__title'), bg_line: first.bottom,
        demo: R('.lp-demo'), values: R('.lp-values')}}; }})()""")
    bottom = max(r["title"]["b"], r["ctas"]["b"], r["note_title"]["b"], r["bg_line"])
    out["390x844"] = check(bottom <= 844, bottom=round(bottom))
    out["390 values after demo"] = check(r["values"]["t"] >= r["demo"]["b"], values_top=round(r["values"]["t"]), demo_bottom=round(r["demo"]["b"]))
    for label, _ in PERSONAS:
        await p.click_text(".segmented__option", label, wait=0.8)
        n = await p.eval(NOTE)
        out[f"390 {label} note in full"] = check(n["scrolls"] <= 1 and n["says_last"] <= n["card"]["b"], inner_scroll=n["scrolls"])
    return out


async def note_gaps(p, base, width):
    await p.viewport(width, 900)
    await p.goto(base + "/", wait=2.5)
    out = {}
    for label, _ in PERSONAS:
        await p.click_text(".segmented__option", label, wait=0.8)
        gap = await p.eval("""(() => { const b = document.querySelector('.lp-demo__note-live .rl-card__body');
          return Math.max(0, b.clientHeight - b.scrollHeight); })()""")
        out[f"{width} {label}"] = check(gap <= 24, empty_px=gap)
    return out


async def no_caps(p, base, theme):
    out = {}
    for path in ("/", "/privacy"):
        await p.viewport(1440, 900, dark=theme == "dark")
        await p.eval(f"localStorage.setItem('readlayer:theme', '{theme}'); true")
        await p.goto(base + path, wait=2.5)
        bad = await p.eval(CAPS)
        out[f"{path} {theme}"] = check(not bad, offenders=bad[:8])
    return out


async def overlaps(p, base, width):
    await p.viewport(width, 900)
    await p.goto(base + "/", wait=2.5)
    margo = await p.eval(f"({RECT})('.lp-demo__margo')")
    text = await p.eval(f"({TEXT_RECTS})('.lp-demo__para, .lp-demo__note-live .rl-card')")
    out = {f"{width} margo": check(not any(hit(margo, t) for t in text), margo=margo)}
    phone = await p.eval(f"({RECT})('.lp-phone')")
    out[f"{width} no phone"] = check(phone is None)
    if phone:
        await p.eval("(() => { const b = document.querySelector('.lp-demo__note-live .rl-card__body'); b.scrollTop = b.scrollHeight; return true; })()")
        await asyncio.sleep(0.3)
        rects = await p.eval(f"({TEXT_RECTS})('.lp-demo__para, .lp-demo__note-live .rl-card, .lp-demo__caption, .lp-problem h2')")
        rects += [margo]
        out[f"{width} phone"] = check(not any(hit(phone, t) for t in rects), phone=phone)
    hs = await p.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    out[f"{width} hscroll"] = check(hs == 0, px=hs)
    return out


async def swap(p, base, width):
    await p.viewport(width, 900)
    await p.send("Page.enable")
    ident = (await p.send("Page.addScriptToEvaluateOnNewDocument", source=SAMPLER))["identifier"]
    await p.send("Network.setCacheDisabled", cacheDisabled=True)
    try:
        await p.goto(base + "/", wait=4)
        samples = await p.eval("window.__slot || []")
    finally:
        await p.send("Page.removeScriptToEvaluateOnNewDocument", identifier=ident)
        await p.send("Network.setCacheDisabled", cacheDisabled=False)
    # 46c: the swap itself must not move anything (last static frame vs first live frame);
    # reflow from the font swap before it is reported here and gated by Lighthouse CLS.
    idx = next((i for i, (_, st) in enumerate(samples) if not st and i > 0 and samples[i - 1][1]), None)
    static_frames = sum(1 for _, st in samples if st)
    heights = [h for h, _ in samples]
    jump = abs(samples[idx][0] - samples[idx - 1][0]) if idx else None
    return {f"{width} swap": check(idx is not None and jump <= 4 and samples[-1][1] is False, frames=len(samples),
                                    static_frames=static_frames, swap_jump_px=jump,
                                    reflow_before_px=(max(heights[:idx]) - min(heights[:idx])) if idx else None)}


async def clip_text(p, base, width):
    """46d: 16:10 tiles, equal heights across a row, text at natural zoom (≈ 18–20px at 1440)."""
    await p.viewport(width, 900)
    await p.goto(base + "/", wait=2.5)
    tiles = await p.eval("""[...document.querySelectorAll('.lp-how .lp-clip')].map(c => { const r = c.getBoundingClientRect();
      return {w: r.width, h: r.height, t: r.top}; })""")
    texts = await p.eval("[...document.querySelectorAll('.lp-how__text')].map(t => Math.round(t.getBoundingClientRect().top))")
    out = {}
    ratios = [round(t["w"] / t["h"], 2) for t in tiles]
    out[f"{width} clip tiles 16:10"] = check(all(abs(r - 1.6) <= 0.02 for r in ratios), ratios=ratios)
    if width >= 768:
        rows_ok = abs(tiles[0]["h"] - tiles[1]["h"]) < 1 and abs(tiles[2]["h"] - tiles[3]["h"]) < 1
        text_ok = texts[0] == texts[1] and texts[2] == texts[3]
        out[f"{width} clip rows aligned"] = check(rows_ok and text_ok, text_tops=texts)
    crop_w = CROPS["crop_css_w"]
    body_px = CROPS.get("body_px", 21)
    px = [round(t["w"] / crop_w[n] * body_px, 1) for t, n in zip(tiles, ("clip-know", "clip-note", "clip-simpler", "clip-map"), strict=False)]
    if width >= 1024:
        out[f"{width} clip text"] = check(all(17.5 <= v <= 20.5 for v in px[:3]), body_text_px=px)
    else:
        out[f"{width} clip text"] = check(all(v >= 16 for v in px[:3]), body_text_px=px)
    step1 = await p.eval("document.querySelector('.lp-how__step .lp-how__text p').textContent")
    out[f"{width} step 1 says right away"] = check("right away" in step1 and "skip" not in step1)
    return out


async def run_all(p, base):
    report = {}
    report.update(await first_views(p, base))
    for w in (1440, 390):
        report.update(await note_gaps(p, base, w))
    for theme in ("light", "dark"):
        report.update(await no_caps(p, base, theme))
    for w in (1024, 1280, 1440, 390):
        report.update(await overlaps(p, base, w))
    for w in (1440, 390):
        report.update(await swap(p, base, w))
        report.update(await clip_text(p, base, w))
    report.update(await clip_text(p, base, 1280))
    return report
