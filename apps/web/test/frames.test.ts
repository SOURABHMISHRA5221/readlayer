// @vitest-environment jsdom
// Decision 67 A4: loading a Background in the "for you" frame, cached apart from the pick.
import type { CardAnnotation } from "@readlayer/annotator";
import { beforeEach, describe, expect, it, vi } from "vitest";

const explain = vi.fn();
vi.mock("../src/lib/api", () => ({ api: { explain: (...args: unknown[]) => explain(...args) } }));

const { loadExplanation, loadFramed } = await import("../src/lib/explanations");

const note = (id: string, kind: "span" | "paragraph" = "span"): CardAnnotation =>
  ({ id, kind, score: 1, paragraph_id: "p0", anchor: { exact: id } }) as unknown as CardAnnotation;

const reply = (used: "pick" | "for_you") => ({
  id: used, kind: "verified", background: `bg ${used}`, author_says: "says", analogy_domain: null, cached: false,
  frames: { pick: "cricket", for_you: "finance", used },
});  // prettier-ignore

beforeEach(() => explain.mockReset());

describe("loadFramed", () => {
  it("asks for frame for_you, keeps it apart from the pick, and passes frames through", async () => {
    explain.mockImplementation((...args: unknown[]) => {
      const target = args[1] as { frame?: string } | undefined;
      return Promise.resolve(reply(target?.frame ? "for_you" : "pick"));
    });
    const pick = await loadExplanation("doc-f", null, note("n1"));
    const fy = await loadFramed("doc-f", null, note("n1"), "for_you", 0);
    expect(explain.mock.calls.map((c) => c[1])).toEqual([{ demand_id: "n1" }, { demand_id: "n1", frame: "for_you" }]);
    expect(pick.frames?.used).toBe("pick");
    expect(fy.frames).toEqual({ pick: "cricket", for_you: "finance", used: "for_you" });
    await loadFramed("doc-f", null, note("n1"), "for_you", 0); // cached
    expect(explain).toHaveBeenCalledTimes(2);
  });

  it("combines with a shift, and paragraphs ask by paragraph", async () => {
    explain.mockResolvedValue(reply("for_you"));
    await loadFramed("doc-g", null, note("n2"), "for_you", 1);
    await loadFramed("doc-g", null, note("m1", "paragraph"), "for_you", 0);
    expect(explain.mock.calls.map((c) => c[1])).toEqual([
      { demand_id: "n2", shift: 1, frame: "for_you" },
      { paragraph_id: "p0", frame: "for_you" },
    ]);
  });

  it("pick goes through the usual loaders", async () => {
    explain.mockResolvedValue(reply("pick"));
    await loadFramed("doc-h", null, note("n3"), "pick", 0);
    await loadFramed("doc-h", null, note("n3"), "pick", -1);
    expect(explain.mock.calls.map((c) => c[1])).toEqual([{ demand_id: "n3" }, { demand_id: "n3", shift: -1 }]);
  });
});
