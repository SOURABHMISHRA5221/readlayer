import { describe, expect, it } from "vitest";

import { layout, type LayoutNode } from "../src/lib/mapLayout";

const nodes: LayoutNode[] = ["finance", "health", "sports"].flatMap((d) =>
  Array.from({ length: 10 }, (_, i) => ({ id: `${d}-${i}`, label: `${d} idea ${i}`, domain: d, weight: 1 - i / 10, rank: i })),
);

describe("knowledge map layout", () => {
  it("is deterministic", () => {
    const a = layout(nodes, ["finance", "health", "sports"], 760, 560);
    const b = layout(nodes, ["finance", "health", "sports"], 760, 560);
    expect(a.nodes.map((n) => [n.x, n.y])).toEqual(b.nodes.map((n) => [n.x, n.y]));
  });

  it("keeps every node inside the canvas and labels never overlap", () => {
    const l = layout(nodes, ["finance", "health", "sports"], 760, 560);
    for (const n of l.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(56);
      expect(n.x).toBeLessThanOrEqual(704);
      expect(n.y).toBeGreaterThanOrEqual(52);
      expect(n.y).toBeLessThanOrEqual(488);
    }
    const labelled = l.nodes.filter((n) => n.showLabel);
    expect(labelled.length).toBeGreaterThan(5);
    for (const a of labelled)
      for (const b of labelled) {
        if (a === b) continue;
        const apart =
          Math.abs(a.x - b.x) > (a.label.length * 6.6 + b.label.length * 6.6) / 2 + 6 ||
          Math.abs(a.y + a.r - (b.y + b.r)) > 15;
        expect(apart).toBe(true);
      }
  });

  it("puts You in the middle only for several domains", () => {
    expect(layout(nodes, ["finance", "health"], 760, 560).center).not.toBeNull();
    expect(layout(nodes.filter((n) => n.domain === "finance"), ["finance"], 760, 560).center).toBeNull();
  });
});

/** The demo personas' shape: 4 topics of 16 ideas. */
const persona: LayoutNode[] = ["economics", "finance", "business", "policy"].flatMap((d) =>
  Array.from({ length: 16 }, (_, i) => ({ id: `${d}-${i}`, label: `${d} idea ${i}`, domain: d, weight: 1 - i / 20, rank: i })),
);
const coords = (l: ReturnType<typeof layout>) => ({
  center: l.center,
  clusters: l.clusters.map((c) => [c.domain, Math.round(c.x * 100) / 100, Math.round(c.labelY * 100) / 100]),
  nodes: l.nodes.map((n) => [n.id, Math.round(n.x * 100) / 100, Math.round(n.y * 100) / 100, n.showLabel]),
});

// Wide layout (decision 45): phones, tablets and 1024px keep the 760px canvas, so its output
// must not move. Snapshot taken from the code before the wide change.
describe("knowledge map layout at 760px and below is unchanged", () => {
  it("three topics at 760×560", () => {
    expect(coords(layout(nodes, ["finance", "health", "sports"], 760, 560))).toMatchSnapshot();
  });
  it("a persona's four topics at 760×600", () => {
    expect(coords(layout(persona, ["economics", "finance", "business", "policy"], 760, 600))).toMatchSnapshot();
  });
  it("one topic at 760×600", () => {
    expect(coords(layout(persona.filter((n) => n.domain === "finance"), ["finance"], 760, 600))).toMatchSnapshot();
  });
});
