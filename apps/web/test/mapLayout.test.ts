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
