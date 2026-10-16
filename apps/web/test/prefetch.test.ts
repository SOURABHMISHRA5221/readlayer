// @vitest-environment jsdom
// Decision 67 L3: in-view prefetch for signed-in consumers, bounded per page and in flight;
// a capped prefetch result is not kept.
import type { CardAnnotation } from "@readlayer/annotator";
import { beforeEach, describe, expect, it, vi } from "vitest";

const explain = vi.fn();
vi.mock("../src/lib/api", () => ({ api: { explain: (...args: unknown[]) => explain(...args) } }));

const { loadExplanation, makePrefetcher, prefetchInView, PREFETCH_MAX } = await import("../src/lib/explanations");

const note = (id: string, score = 1): CardAnnotation =>
  ({ id, kind: "span", score, anchor: { exact: id } }) as unknown as CardAnnotation;

const reply = (capped: boolean) => ({
  id: "x",
  kind: capped ? "definition" : "verified",
  background: null,
  author_says: null,
  analogy_domain: null,
  cached: false,
  capped,
});

describe("makePrefetcher", () => {
  it("starts each id once, at most max in all and inFlight at a time", async () => {
    const resolvers: (() => void)[] = [];
    const started: string[] = [];
    const q = makePrefetcher(
      (id) => {
        started.push(id);
        return new Promise<void>((r) => resolvers.push(r));
      },
      4,
      2,
      ["top"],
    );
    for (const id of ["a", "a", "top", "b", "c", "d", "e"]) q.request(id);
    expect(started).toEqual(["a", "b"]); // 2 in flight
    expect(q.started).toBe(4); // "top" counted, then a, b, c: d and e are past the total
    resolvers.shift()!();
    await Promise.resolve();
    await Promise.resolve();
    expect(started).toEqual(["a", "b", "c"]);
  });
});

describe("prefetchInView", () => {
  it("does nothing for demo consumers (their caps are for clicks)", () => {
    const observe = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe = observe;
        disconnect() {}
      },
    );
    const root = document.createElement("div");
    root.innerHTML = '<span class="rl-mark" data-rl-id="a">a</span>';
    prefetchInView(root, "doc", "newcomer", [note("a")])();
    expect(observe).not.toHaveBeenCalled();
    prefetchInView(root, "doc", null, [note("a")])();
    expect(observe).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("caps a page at PREFETCH_MAX", () => {
    expect(PREFETCH_MAX).toBe(10);
  });
});

describe("capped prefetch", () => {
  beforeEach(() => explain.mockReset());

  it("is not kept, so a click asks again; a click's capped card is kept", async () => {
    explain.mockResolvedValue(reply(true));
    await loadExplanation("doc-c", null, note("n1"), true);
    await loadExplanation("doc-c", null, note("n1"));
    expect(explain).toHaveBeenCalledTimes(2);
    await loadExplanation("doc-c", null, note("n1"));
    expect(explain).toHaveBeenCalledTimes(2);
  });

  it("keeps a verified prefetch", async () => {
    explain.mockResolvedValue(reply(false));
    await loadExplanation("doc-v", null, note("n2"), true);
    await loadExplanation("doc-v", null, note("n2"));
    expect(explain).toHaveBeenCalledTimes(1);
  });
});
