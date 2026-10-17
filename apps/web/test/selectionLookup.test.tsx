// Decision 70 Fix 3: what "Explain" on a selection opens.
import type { CardAnnotation, ParagraphMarker } from "@readlayer/annotator";
import { describe, expect, it } from "vitest";

import { afterPlaced, planAsk, paragraphFallback } from "../src/lib/selectionLookup";

const span = (id: string, concept_id: string, paragraph_id = "p1"): CardAnnotation => ({
  id, kind: "span", anchor: { exact: id, prefix: "", suffix: "" }, paragraph_id, score: 0.5,
  concept_id, label: id, definition: `${id} defined.`, domain: "finance", prerequisites: [],
});  // prettier-ignore

const marker = (paragraph_id: string): ParagraphMarker => ({
  id: `para:${paragraph_id}`, kind: "paragraph", paragraph_id, score: 0,
});  // prettier-ignore

const ASK = { paragraph_id: "p1", start: 4, end: 19 };
const page = { spans: [span("fca", "c_fca")], markers: [marker("p5")] };

describe("planAsk", () => {
  it("a term not on the page is added and opened", async () => {
    const hit = span("insider", "c_insider_trading");
    expect(await planAsk(ASK, page, async () => hit)).toEqual({ add: hit, open: "insider" });
  });

  it("a term whose concept is already marked opens that mark, no second one", async () => {
    const again = span("fca2", "c_fca");
    expect(await planAsk(ASK, page, async () => again)).toEqual({ open: "fca" });
    expect(await planAsk(ASK, page, async () => span("fca", "c_fca"))).toEqual({ open: "fca" });
  });

  it("no term → the paragraph's card, its ¶ added when absent", async () => {
    expect(await planAsk(ASK, page, async () => null)).toEqual({ add: marker("p1"), open: "para:p1" });
    const onP5 = { ...ASK, paragraph_id: "p5" };
    expect(await planAsk(onP5, page, async () => null)).toEqual({ open: "para:p5" });
  });

  it("a failed lookup → the paragraph's card", async () => {
    const failing = async () => {
      throw new Error("offline");
    };
    expect(await planAsk(ASK, page, failing)).toEqual({ add: marker("p1"), open: "para:p1" });
  });
});

describe("paragraphFallback", () => {
  it("a looked-up note that couldn't be placed falls back to its paragraph's card", () => {
    expect(paragraphFallback("p3", page.markers)).toEqual({ add: marker("p3"), open: "para:p3" });
    expect(paragraphFallback("p5", page.markers)).toEqual({ open: "para:p5" });
  });
});

describe("afterPlaced", () => {
  const result = { resolved: ["fca"], paragraphs: ["para:p5"], unresolved: ["insider"] };
  it("opens a placed word or ¶, falls back for one that couldn't be placed, else waits", () => {
    expect(afterPlaced("fca", result)).toBe("open");
    expect(afterPlaced("para:p5", result)).toBe("open");
    expect(afterPlaced("insider", result)).toBe("fallback");
    expect(afterPlaced("later", result)).toBe("wait");
  });
});

