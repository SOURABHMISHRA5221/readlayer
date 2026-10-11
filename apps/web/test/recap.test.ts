import { describe, expect, it } from "vitest";

import { bandMoves, mergeRecapView, movesExcept, nextReads, notesForView, teaching } from "../src/lib/recap";

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

describe("recap labels across a Know this? refresh (decision 46d)", () => {
  const prompt = { kind: "prompt", concept_id: "c_hedging", label: "Hedging" };
  const span = (id: string, label: string) => ({ concept_id: id, label });

  it("keep the answered prompt's concept and only add within one view", () => {
    const first = mergeRecapView({ key: "", labels: {} }, "a|newcomer|balanced", [span("c_bps", "Basis points")], [prompt]);
    expect(first.labels).toEqual({ c_bps: "Basis points", c_hedging: "Hedging" });
    // The refetch after "Yes": no prompt, and the term isn't a span.
    const refreshed = mergeRecapView(first, "a|newcomer|balanced", [span("c_bps", "Basis points")], []);
    expect(refreshed).toBe(first); // unchanged, so the "before" snapshot isn't re-taken
    // After "Not really" on a later answer the refetch adds a span: it joins, nothing is lost.
    const grown = mergeRecapView(first, "a|newcomer|balanced", [span("c_fwd", "Forwards")], []);
    expect(grown.labels).toEqual({ c_bps: "Basis points", c_hedging: "Hedging", c_fwd: "Forwards" });
  });

  it("start fresh for a new view (persona, density or article)", () => {
    const first = mergeRecapView({ key: "", labels: {} }, "a|newcomer|balanced", [span("c_bps", "Basis points")], [prompt]);
    const other = mergeRecapView(first, "a|trader|balanced", [span("c_tight", "Monetary tightening")], []);
    expect(other).toEqual({ key: "a|trader|balanced", labels: { c_tight: "Monetary tightening" } });
  });
});

describe("recap after a persona or density switch (decision 46d)", () => {
  it("ignores the previous view's notes until the new view's response arrives", () => {
    const old = { annotations: [{ concept_id: "c_bps", label: "Basis points" }], extras: [] };
    const fresh = { annotations: [{ concept_id: "c_tight", label: "Monetary tightening" }], extras: [] };
    const view = "a|trader|balanced";
    // The switch: old notes still on screen, tagged with the old view → nothing to merge or snapshot.
    expect(notesForView(old, "a|newcomer|balanced", view)).toBeNull();
    // The first matching response is what the new view's labels (and so its snapshot) come from.
    const current = notesForView(fresh, view, view)!;
    const labels = mergeRecapView({ key: "a|newcomer|balanced", labels: { c_bps: "Basis points" } }, view, current.annotations, current.extras);
    expect(labels).toEqual({ key: view, labels: { c_tight: "Monetary tightening" } });
  });
});
