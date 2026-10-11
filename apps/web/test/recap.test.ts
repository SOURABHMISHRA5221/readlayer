import { describe, expect, it } from "vitest";

import { bandMoves, teaching } from "../src/lib/recap";

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
});
