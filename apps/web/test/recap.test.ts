import { describe, expect, it } from "vitest";

import { bandMoves, movesExcept, nextReads, teaching } from "../src/lib/recap";

describe("recap", () => {
  it("is empty when nothing changed during the page view", () => {
    expect(bandMoves({ a: "heard of", b: "unaware" }, { a: "heard of", b: "unaware" }, {})).toEqual([]);
  });

  it("lists rises first with their labels", () => {
    const moves = bandMoves(
      { a: "heard of", b: "understands", c: "unaware" },
      { a: "understands", b: "heard of", c: "unaware" },
      { a: "Yield curve", b: "Repo rate" },
    );
    expect(moves.map((m) => [m.label, m.from, m.to, m.up])).toEqual([
      ["Yield curve", "heard of", "understands", true],
      ["Repo rate", "understands", "heard of", false],
    ]);
  });

  it("only items that teach an unknown concept count as teaching", () => {
    const items = [{ id: 1, triggers: [{ id: "x" }] }, { id: 2, triggers: [{ id: "tp" }] }, { id: 3, triggers: [{ id: "tp" }] }, { id: 4, triggers: [{ id: "tp" }] }];
    expect(teaching(items, new Set(["tp"])).map((i) => i.id)).toEqual([2, 3]);
    expect(teaching(items, new Set())).toEqual([]);
  });

  it("a Not really answer is one row, not a band move as well", () => {
    const moves = bandMoves({ tp: "heard of", yc: "heard of" }, { tp: "unaware", yc: "understands" }, { tp: "Term premium", yc: "Yield curve" });
    expect(movesExcept(moves, new Set(["tp"])).map((m) => m.conceptId)).toEqual(["yc"]);
  });

  it("a Yes answer stays a band move (with its Undo)", () => {
    const moves = bandMoves({ yc: "heard of", tp: "heard of" }, { yc: "understands", tp: "unaware" }, {});
    const answers = new Map([["yc", { known: true }], ["tp", { known: false }]]);
    const unknown = new Set([...answers].filter(([, a]) => !a.known).map(([id]) => id));
    expect(movesExcept(moves, unknown).map((m) => m.conceptId)).toEqual(["yc"]);
  });

  it("falls back to Up next's top two under a neutral label", () => {
    const items = [{ id: 1, triggers: [{ id: "x" }] }, { id: 2, triggers: [{ id: "y" }] }, { id: 3, triggers: [] }];
    expect(nextReads(items, new Set(["tp"]))).toEqual({ items: items.slice(0, 2), teaches: false });
    expect(nextReads(items, new Set(["y"]))).toEqual({ items: [items[1]], teaches: true });
  });
});
