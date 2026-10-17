import { describe, expect, it } from "vitest";

import { readingProgress } from "../src/lib/readingProgress";
import { minutesLeft, placeInArticle, spineTicks, type SpineNote } from "../src/lib/spine";

// Three paragraphs joined by "\n\n", as the API numbers its anchors (40 + 2 + 60 + 2 + 100).
const paragraphs = [
  { id: "p1", text: "a".repeat(40) },
  { id: "p2", text: "The repo rate is what banks pay to borrow." + "b".repeat(18) },
  { id: "p3", text: "c".repeat(100) },
];
const TOTAL = 204;

// Cut from a real /annotations response: article-level offsets, `level` only on refreshers.
const note = (id: string, paragraph_id: string, start: number | undefined, exact = "x", level?: "new" | "refresher"): SpineNote => ({
  id,
  paragraph_id,
  anchor: { exact, prefix: "", suffix: "", start, end: start === undefined ? undefined : start + exact.length },
  level,
});

describe("spine ticks", () => {
  it("places a note by its article-level offset over the joined length", () => {
    const ticks = spineTicks([note("a", "p1", 0), note("b", "p2", 46), note("c", "p3", 203)], paragraphs);
    expect(ticks.map((t) => t.id)).toEqual(["a", "b", "c"]);
    expect(ticks[0]?.at).toBe(0);
    expect(ticks[1]?.at).toBeCloseTo(46 / TOTAL, 6);
    expect(ticks[2]?.at).toBeCloseTo(203 / TOTAL, 6);
  });

  it("sorts by position, whatever order the notes arrive in", () => {
    const ticks = spineTicks([note("late", "p3", 150), note("early", "p1", 10)], paragraphs);
    expect(ticks.map((t) => t.id)).toEqual(["early", "late"]);
  });

  it("falls back to the paragraph's start plus where the quote sits when there is no offset", () => {
    const [tick] = spineTicks([note("r", "p2", undefined, "repo rate")], paragraphs);
    expect(tick?.at).toBeCloseTo((42 + 4) / TOTAL, 6);
  });

  it("uses the paragraph's start when the quote isn't found", () => {
    const [tick] = spineTicks([note("r", "p3", undefined, "not in the text")], paragraphs);
    expect(tick?.at).toBeCloseTo(104 / TOTAL, 6);
  });

  it("skips a note without an offset whose paragraph is unknown", () => {
    expect(spineTicks([note("gone", "p9", undefined)], paragraphs)).toEqual([]);
  });

  it("defaults the level to new and keeps refresher", () => {
    const ticks = spineTicks([note("a", "p1", 1), note("b", "p1", 2, "x", "refresher")], paragraphs);
    expect(ticks.map((t) => t.level)).toEqual(["new", "refresher"]);
  });

  it("never leaves the track", () => {
    const [tick] = spineTicks([note("a", "p3", 9999)], paragraphs);
    expect(tick?.at).toBe(1);
    expect(spineTicks([note("a", "p1", 0)], [])).toEqual([]);
  });
});

describe("place in the article", () => {
  // The share of the prose above the middle of the screen.
  it("is 0 before the article reaches the middle of the screen", () => {
    expect(placeInArticle(700, 3000, 900, false)).toBe(0);
  });
  it("is the share above mid-screen part-way through", () => {
    expect(placeInArticle(-150, 3000, 900, false)).toBeCloseTo(0.2, 6); // (450 + 150) / 3000
  });
  it("is 1 once the article's end passes mid-screen", () => {
    expect(placeInArticle(-2600, 3000, 900, false)).toBe(1);
  });
  it("is 1 at the page's end even when a short article's end never reaches mid-screen", () => {
    expect(placeInArticle(100, 500, 900, false)).toBeCloseTo(0.7, 6);
    expect(placeInArticle(100, 500, 900, true)).toBe(1);
  });
  it("copes with an article that has no height yet", () => {
    expect(placeInArticle(0, 0, 900, false)).toBe(0);
  });
});

describe("minutes left", () => {
  it("rounds up, so a started minute still counts", () => {
    expect(minutesLeft(1380, 0)).toBe(6); // the same 230 words a minute as the byline
    expect(minutesLeft(1380, 0.5)).toBe(3);
    expect(minutesLeft(1380, 0.9)).toBe(1);
  });
  it("is 0 at the end", () => {
    expect(minutesLeft(1380, 1)).toBe(0);
  });
});

describe("reading progress (the top line)", () => {
  // The numbers ProgressBar produced before this function moved out of it.
  it.each([
    [0, 3000, 900, 0],
    [-1230, 3000, 900, 0.5],
    [-2460, 3000, 900, 1],
    [-5000, 3000, 900, 1],
    [200, 3000, 900, 0],
    [0, 400, 900, 1],
  ])("top %i of a %i page in a %i window is %f", (top, height, viewport, want) => {
    expect(readingProgress(top, height, viewport)).toBeCloseTo(want, 6);
  });
});

describe("¶ notes on the spine (decision 70)", () => {
  it("a ¶ note ticks at its paragraph's start, drawn as a paragraph tick", () => {
    const para: SpineNote = { id: "para:p2", kind: "paragraph", paragraph_id: "p2", anchor: { exact: "", prefix: "", suffix: "" } };
    const ticks = spineTicks([para], paragraphs);
    expect(ticks).toEqual([{ id: "para:p2", at: 42 / TOTAL, level: "paragraph" }]);
  });
});
