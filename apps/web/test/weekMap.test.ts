import { describe, expect, it } from "vitest";

import type { Domain, OverviewNode } from "../src/lib/profileApi";
import { clusterDots, DOT_R, miniMapNodes, TILE_H, TILE_W, topicTiles, weekLine } from "../src/lib/weekMap";

const SIX: Domain[] = ["economics", "finance", "business", "policy", "technology", "science"];

const node = (domain: Domain, i: number, over: Partial<OverviewNode> = {}): OverviewNode => ({
  id: `${domain}_${i}`,
  label: `${domain} idea ${i}`,
  domain,
  band: "understands",
  ready: false,
  goal: false,
  weight: 1 - i / 100,
  definition: "",
  recent: [],
  rose_this_week: false,
  ...over,
});

/** 16 nodes a topic, as the overview caps them (12 solid + 4 ready). */
const overview = (domains: Domain[], risers: Record<string, number[]> = {}) => ({
  domains,
  nodes: domains.flatMap((d) =>
    Array.from({ length: 16 }, (_, i) => node(d, i, { ready: i >= 12, rose_this_week: (risers[d] ?? []).includes(i) })),
  ),
});

describe("mini-map selection", () => {
  it("keeps at most 8 a topic and 24 in all, shared evenly", () => {
    const picked = miniMapNodes(overview(SIX));
    expect(picked).toHaveLength(24);
    for (const d of SIX) expect(picked.filter((n) => n.domain === d)).toHaveLength(4);
    expect(miniMapNodes(overview(SIX.slice(0, 2)))).toHaveLength(16);
  });

  it("puts this week's risers first and never drops one for an idea that didn't move", () => {
    const picked = miniMapNodes(overview(SIX, { finance: [9, 10, 11, 5, 6, 7] }));
    const finance = picked.filter((n) => n.domain === "finance");
    expect(finance.map((n) => n.id)).toEqual(["finance_5", "finance_6", "finance_7", "finance_9", "finance_10", "finance_11"]);
    expect(picked).toHaveLength(24);
  });

  it("then known ideas by weight, then ready-to-learn ones, with ids breaking ties", () => {
    const ov = { domains: ["law"] as Domain[], nodes: [node("law", 3, { ready: true, weight: 1 }), node("law", 2, { weight: 0.5 }), node("law", 1, { weight: 0.5 }), node("law", 0, { weight: 0.9 })] };
    expect(miniMapNodes(ov).map((n) => n.id)).toEqual(["law_0", "law_1", "law_2", "law_3"]);
  });

  it("keeps a place for what the reader is ready to learn next: up to 2 rings a topic", () => {
    const picked = miniMapNodes(overview(SIX.slice(0, 4))); // a demo persona: 6 dots a topic
    expect(picked.filter((n) => n.domain === "finance").map((n) => n.id)).toEqual(
      ["finance_0", "finance_1", "finance_2", "finance_3", "finance_12", "finance_13"],
    );
    const four = miniMapNodes(overview(SIX)).filter((n) => n.domain === "policy"); // 4 dots: one ring
    expect(four.map((n) => n.ready)).toEqual([false, false, false, true]);
  });

  it("fills with rings when a topic has few known ideas, and with known ideas when it has no rings", () => {
    const few = { domains: ["law"] as Domain[], nodes: [node("law", 0), ...[1, 2, 3, 4].map((i) => node("law", i, { ready: true }))] };
    expect(miniMapNodes(few).map((n) => n.id)).toEqual(["law_0", "law_1", "law_2", "law_3", "law_4"]);
    const solid = { domains: ["law"] as Domain[], nodes: [0, 1, 2].map((i) => node("law", i)) };
    expect(miniMapNodes(solid).map((n) => n.id)).toEqual(["law_0", "law_1", "law_2"]);
  });

  it("is the same for the same input", () => {
    const ov = overview(SIX, { science: [2] });
    expect(miniMapNodes(ov)).toEqual(miniMapNodes(ov));
  });
});

describe("topic tiles", () => {
  it("makes one tile a topic that has ideas, in the overview's order, with its counts", () => {
    const ov = overview(["finance", "health"], { finance: [0, 13] });
    const tiles = topicTiles({ domains: ["finance", "sports", "health"], nodes: ov.nodes });
    expect(tiles.map((t) => t.domain)).toEqual(["finance", "health"]);
    expect(tiles[0]).toMatchObject({ rose: 2 });
    expect(tiles[0]).not.toHaveProperty("known"); // the overview caps a topic at 12: not a count to show
    expect(tiles[0]?.dots).toHaveLength(8);
    expect(tiles[0]?.dots[0]).toMatchObject({ id: "finance_0", rose: true });
  });
});

describe("cluster dots", () => {
  it.each([1, 2, 3, 4, 5, 6, 7, 8])("%i dots sit inside the tile and never overlap", (count) => {
    const dots = clusterDots(count);
    expect(dots).toHaveLength(count);
    const ring = DOT_R + 2.5; // a riser's ring
    for (const d of dots) {
      expect(d.x - ring).toBeGreaterThanOrEqual(0);
      expect(d.x + ring).toBeLessThanOrEqual(TILE_W);
      expect(d.y - ring).toBeGreaterThanOrEqual(0);
      expect(d.y + ring).toBeLessThanOrEqual(TILE_H);
    }
    for (const a of dots) for (const b of dots) if (a !== b) expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(2 * DOT_R);
  });

  it("is deterministic and starts in the middle", () => {
    expect(clusterDots(8)).toEqual(clusterDots(8));
    expect(clusterDots(1)[0]).toEqual({ x: TILE_W / 2, y: TILE_H / 2 });
  });
});

describe("the week in a line", () => {
  const rose = (labels: string[]) => labels.map((label, i) => node("finance", i, { label, rose_this_week: true }));
  it("says so when nothing moved", () => {
    expect(weekLine([node("finance", 0)])).toBe("Nothing moved up yet this week");
  });
  it("names one", () => {
    expect(weekLine(rose(["Repo rate"]))).toBe("1 idea moved up this week: Repo rate");
  });
  it("names three", () => {
    expect(weekLine(rose(["Repo rate", "Yield curve", "Term premium"]))).toBe("3 ideas moved up this week: Repo rate, Yield curve and Term premium");
  });
  it("names three of five and counts the rest", () => {
    expect(weekLine(rose(["A", "B", "C", "D", "E"]))).toBe("5 ideas moved up this week: A, B, C and 2 more");
  });
});
