"""Decision 46 checks for tools/shots/landing.py (plan P6 and round 1): first views, the open note,
no tracked caps, Margo and phone overlaps, the static → live swap, and clip legibility.

Each check returns its numbers and a pass flag; landing.py prints them and exits non-zero on a fail.
"""

import asyncio
from pathlib import Path

PERSONAS = (("Software engineer", "Basis points"), ("Cricket fan", "Monetary tightening"), ("Policy student", "Basis points"))
MEDIA = Path(__file__).resolve().parents[2] / "apps/web/public/landing"
LOOPS = ("clip-know", "clip-note", "clip-simpler", "clip-map")
# Decision 46e budgets: loops ≤ 600 KB (2x and 1x files), posters ≤ 120 KB; stills ≤ 120 KB at 1x
# and ≤ 250 KB at 2x (S2).
LOOP_MAX, POSTER_MAX, STILL_MAX = 600_000, 120_000, {"": 120_000, "@2x": 250_000}
# Shortfalls reported to Sourabh rather than forced (none open: 46e settled the phone clip text).
KNOWN: set[str] = set()

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


def media_budgets() -> dict:
    """46e S3/S5: every loop file ≤ 600 KB, posters ≤ 120 KB, stills within their budgets."""
    out = {}
    for name in LOOPS:
        sizes = {f.name: f.stat().st_size for f in MEDIA.glob(f"{name}*") if f.suffix in (".webm", ".mp4")}
        poster = (MEDIA / f"{name}-poster.webp").stat().st_size
        out[f"{name} files"] = check(len(sizes) == 4 and max(sizes.values()) <= LOOP_MAX and poster <= POSTER_MAX,
                                     largest=max(sizes.values(), default=None), poster=poster, files=len(sizes))
    for still in ("shot-reader", "shot-feed", "shot-phone", "shot-media", "shot-extension", "shot-popup"):  # + decision 61
        sizes = {f.name: f.stat().st_size for f in MEDIA.glob(f"{still}*")}
        ok = len(sizes) == 4 and all(v <= STILL_MAX["@2x" if "@2x" in k else ""] for k, v in sizes.items())
        out[f"{still} files"] = check(ok, sizes=sizes)
    return out


async def clips_and_frames(p, base, width):
    """46e: framed 16:10 loops with equal heights and aligned text; zoom ≤ 1.15; step 1's copy."""
    await p.viewport(width, 900)
    await p.goto(base + "/", wait=2.5)
    tiles = await p.eval("""[...document.querySelectorAll('.lp-how .lp-clip')].map(c => { const r = c.getBoundingClientRect();
      return {w: r.width, h: r.height, zoom: parseFloat(c.style.getPropertyValue('--clip-zoom') || '1')}; })""")
    texts = await p.eval("[...document.querySelectorAll('.lp-how__text')].map(t => Math.round(t.getBoundingClientRect().top))")
    framed = await p.eval("[...document.querySelectorAll('.lp-how .lp-clip')].every(c => !!c.closest('.lp-device--laptop'))")
    out = {}
    ratios = [round(t["w"] / t["h"], 2) for t in tiles]
    out[f"{width} loops framed 16:10"] = check(framed and all(abs(r - 1.6) <= 0.02 for r in ratios), ratios=ratios)
    if width >= 768:
        rows_ok = abs(tiles[0]["h"] - tiles[1]["h"]) < 1 and abs(tiles[2]["h"] - tiles[3]["h"]) < 1
        out[f"{width} loop rows aligned"] = check(rows_ok and texts[0] == texts[1] and texts[2] == texts[3], text_tops=texts)
    out[f"{width} zoom ≤ 1.15"] = check(all(t["zoom"] <= 1.15 for t in tiles), zooms=[t["zoom"] for t in tiles])
    step1 = await p.eval("document.querySelector('.lp-how__step .lp-how__text p').textContent")
    out[f"{width} step 1 says right away"] = check("right away" in step1 and "skip" not in step1)
    final = await p.eval("!!document.querySelector('.lp-final .lp-device--laptop .lp-clip')")
    out[f"{width} final CTA framed loop"] = check(final)
    return out


async def device_media(p, base, width):
    """46e S2: each device downloads only its own stills (phone below 1024, the pair at ≥ 1024)."""
    await p.viewport(width, 900)
    await p.goto(base + "/", wait=2)
    await p.eval("(async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); } return true; })()")
    await asyncio.sleep(1.5)
    names = await p.eval("performance.getEntriesByType('resource').map(e => e.name).filter(n => n.includes('/landing/shot-'))")
    phone = any("shot-phone" in n for n in names)
    pair = any("shot-feed" in n or "shot-reader" in n for n in names)
    ok = (pair and not phone) if width >= 1024 else (phone and not pair)
    return {f"{width} device stills": check(ok, requested=sorted({n.rsplit("/", 1)[1] for n in names}))}


async def section_gaps(p, base, width):
    """46e S4: breathing room between sections (≥ 72px at 390, ≥ 120px at 1440)."""
    await p.viewport(width, 900)
    await p.goto(base + "/", wait=2)
    gaps = await p.eval("""(() => { const secs = [...document.querySelectorAll('.lp-hero, main > section')];
      const content = s => { const kids = [...s.children].filter(k => k.getBoundingClientRect().height > 0);
        return {t: Math.min(...kids.map(k => k.getBoundingClientRect().top)), b: Math.max(...kids.map(k => k.getBoundingClientRect().bottom))}; };
      const out = []; for (let i = 1; i < secs.length; i++) out.push(Math.round(content(secs[i]).t - content(secs[i - 1]).b));
      return out; })()""")
    need = 120 if width >= 1440 else 72
    return {f"{width} section gaps": check(min(gaps) >= need, smallest=min(gaps), need=need, gaps=gaps)}


FONT_CHECK = """(async () => {
  const preloads = [...document.querySelectorAll('link[rel=preload][as=font]')].map(l => l.href);
  const types = await Promise.all(preloads.map(u => fetch(u).then(r => [u.split('/').pop(), r.status, r.headers.get('content-type')])));
  const faces = ['400 16px "Schibsted Grotesk"', '800 16px "Schibsted Grotesk"', '400 16px "Source Serif 4"',
                 '600 16px "Source Serif 4"', 'italic 400 16px "Source Serif 4"'];
  await Promise.all(faces.map(f => document.fonts.load(f, 'Ab ₹25 crore')));
  const status = [...document.fonts].filter(f => /Schibsted|Source Serif/.test(f.family)).map(f => f.family + ' ' + f.style + ' ' + f.unicodeRange.slice(0, 6) + ': ' + f.status);
  // ₹ in each face must be its own glyph: its width differs from the system fallback's.
  const c = document.createElement('canvas').getContext('2d');
  const w = font => { c.font = font; return c.measureText('₹').width; };
  const rupee = [['"Schibsted Grotesk"', 'Arial'], ['"Source Serif 4"', 'Georgia'], ['italic', 'Georgia']].map(([face, fb]) => {
    const f = face === 'italic' ? 'italic 400 100px "Source Serif 4"' : '400 100px ' + face;
    const g = face === 'italic' ? 'italic 400 100px ' + fb : '400 100px ' + fb;
    return [face, document.fonts.check(f.replace('100px', '16px'), '₹'), Math.round(w(f)), Math.round(w(g))];
  });
  return {types, status, rupee};
})()"""


async def fonts(p, base):
    """Decision 47: self-hosted fonts load (a bad path would come back as index.html), and ₹ is a
    real glyph in each face."""
    out = {}
    for path in ("/", "/privacy"):
        await p.viewport(1440, 900)
        await p.goto(base + path, wait=2.5)
        r = await p.eval(FONT_CHECK)
        types_ok = len(r["types"]) == 2 and all(t[1] == 200 and t[2] == "font/woff2" for t in r["types"])
        loaded = [x for x in r["status"] if "U+0000" in x or "U+20B9" in x]
        status_ok = loaded and all(x.endswith("loaded") for x in loaded)
        rupee_ok = all(ok and web != fb for _, ok, web, fb in r["rupee"])
        out[f"{path} fonts"] = check(types_ok and status_ok and rupee_ok, types=r["types"], status=r["status"], rupee=r["rupee"])
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
    report.update(media_budgets())
    report.update(await fonts(p, base))
    for w in (1440, 390):
        report.update(await swap(p, base, w))
        report.update(await device_media(p, base, w))
        report.update(await section_gaps(p, base, w))
    for w in (1440, 1280, 390):
        report.update(await clips_and_frames(p, base, w))
    return report
