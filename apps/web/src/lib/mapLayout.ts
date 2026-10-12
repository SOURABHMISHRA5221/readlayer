/**
 * Knowledge map layout (Design pass C7): "You" in the middle, one cluster per domain on a ring,
 * nodes spiralling out from their cluster centre, then a fixed number of collision passes.
 * Deterministic for the same input (no randomness), so the map doesn't jump between renders.
 */

export interface LayoutNode {
  id: string;
  label: string;
  domain: string;
  weight: number; // 0..1
  rank: number; // within its domain: 0 = most important
}

export interface Placed extends LayoutNode {
  x: number;
  y: number;
  r: number;
  showLabel: boolean;
}

export interface Layout {
  width: number;
  height: number;
  center: { x: number; y: number } | null; // null when a single domain is shown
  clusters: { domain: string; x: number; y: number; labelY: number }[];
  nodes: Placed[];
}

const GOLDEN = 2.399963;
const MIN_GAP = 30;
const PASSES = 80;
const CHAR_W = 6.6;
/** The canvas phones, tablets and 1024px get (scaled into the box); above it the map is laid
 *  out at the box's own size (Wide layout, decision 45). */
const NARROW_W = 760;
const NARROW_H = 600;
const MAX_W = 1160;
const STEP = 40; // the layout only changes at these steps while a window is resized
const EDGE = { left: 56, right: 56, top: 52, bottom: 72 };

/** The canvas for a box of this width: today's 760×600 under 760px, else the box's width in
 *  whole steps and a taller 4:3-ish height. */
export function mapSize(boxWidth: number): { width: number; height: number } {
  if (boxWidth < NARROW_W) return { width: NARROW_W, height: NARROW_H };
  const width = Math.min(MAX_W, Math.floor(boxWidth / STEP) * STEP);
  return { width, height: Math.min(780, Math.max(680, Math.round(width * 0.75))) };
}

export const radius = (weight: number) => 6 + Math.max(0, Math.min(1, weight)) * 7;

export function layout(nodes: readonly LayoutNode[], domains: readonly string[], width: number, height: number): Layout {
  const single = domains.length <= 1;
  const cx = width / 2;
  const cy = height / 2 - 10;
  const ring = single ? 0 : Math.min(width * 0.37, height * 0.4);
  // A wide canvas spreads the clusters on an ellipse, so they reach its sides; up to 760px the
  // output is exactly what it always was (test/mapLayout.test.ts pins it).
  const wide = width > NARROW_W;
  const rx = wide && !single ? width * 0.37 : ring;
  const ry = (wide && !single ? height * 0.4 : ring) * 0.82;
  const centres = new Map<string, { x: number; y: number }>();
  domains.forEach((d, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, domains.length);
    centres.set(d, { x: cx + Math.cos(a) * rx, y: cy + Math.sin(a) * ry });
  });
  const spread = single ? 1.9 : 1;
  const pts: Placed[] = nodes.map((n) => {
    const c = centres.get(n.domain) ?? { x: cx, y: cy };
    const t = n.rank * GOLDEN;
    const rr = n.rank === 0 ? 0 : (18 + Math.sqrt(n.rank) * 26) * spread;
    return { ...n, x: c.x + Math.cos(t) * rr * 1.2, y: c.y + Math.sin(t) * rr * 0.8, r: radius(n.weight), showLabel: false };
  });
  for (let it = 0; it < PASSES; it++) {
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const a = pts[i] as Placed;
        const b = pts[j] as Placed;
        const dx = b.x - a.x;
        const dy = (b.y - a.y) * 1.5;
        const d = Math.hypot(dx, dy) || 1;
        const min = MIN_GAP + (a.r + b.r) / 2;
        if (d < min) {
          const push = (min - d) / 2 / d;
          a.x -= dx * push * 0.5;
          a.y -= dy * push * 0.3;
          b.x += dx * push * 0.5;
          b.y += dy * push * 0.3;
        }
      }
    }
    if (!single) keepClearOfYou(pts, cx, cy);
    // On a wide canvas the edges take part in every pass, so dots pushed against one are
    // spread along it instead of being piled there by the final clamp.
    if (wide) keepInside(pts, width, height);
  }
  keepInside(pts, width, height);
  labelNodes(pts);
  const clusters = domains.map((d) => {
    const mine = pts.filter((p) => p.domain === d);
    const c = centres.get(d) ?? { x: cx, y: cy };
    const x = mine.length ? mine.reduce((s, p) => s + p.x, 0) / mine.length : c.x;
    const top = mine.length ? Math.min(...mine.map((p) => p.y - p.r)) : c.y;
    return { domain: d, x: Math.max(48, Math.min(width - 48, x)), y: c.y, labelY: Math.max(18, top - 16) };
  });
  return { width, height, center: single ? null : { x: cx, y: cy }, clusters, nodes: pts };
}

function keepInside(pts: Placed[], width: number, height: number): void {
  for (const p of pts) {
    p.x = Math.max(EDGE.left, Math.min(width - EDGE.right, p.x));
    p.y = Math.max(EDGE.top, Math.min(height - EDGE.bottom, p.y));
  }
}

/** Keep nodes clear of the "You" disc in the middle. */
function keepClearOfYou(pts: Placed[], cx: number, cy: number): void {
  for (const p of pts) {
    const dx = p.x - cx;
    const dy = p.y - cy;
    const d = Math.hypot(dx, dy) || 1;
    if (d < 48) {
      p.x = cx + (dx / d) * 48;
      p.y = cy + (dy / d) * 48;
    }
  }
}

/** Label the most important nodes first, skipping any whose label would overlap another. */
function labelNodes(pts: Placed[]): void {
  const boxes: { x: number; y: number; w: number }[] = [];
  const order = [...pts].sort((a, b) => a.rank - b.rank || b.weight - a.weight || a.id.localeCompare(b.id));
  for (const p of order) {
    const w = p.label.length * CHAR_W;
    const y = p.y + p.r + 13;
    const clear = boxes.every((q) => Math.abs(q.x - p.x) > (q.w + w) / 2 + 6 || Math.abs(q.y - y) > 15);
    const offDots = pts.every((o) => o === p || Math.abs(o.x - p.x) > w / 2 + o.r || Math.abs(o.y - (y - 4)) > o.r + 8);
    if (clear && offDots) {
      p.showLabel = true;
      boxes.push({ x: p.x, y, w });
    }
  }
}
