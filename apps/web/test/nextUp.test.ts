// @vitest-environment jsdom
// Decision 67 N3: card chips from article-basis items, the shared opener, rec_shown once a page.
import { beforeEach, describe, expect, it, vi } from "vitest";

const openWeb = vi.fn();
const recommendations = vi.fn();
class FakeApiError extends Error {
  constructor(
    readonly kind: string,
    readonly status: number | null,
  ) {
    super(kind);
  }
}
vi.mock("../src/lib/api", () => ({
  ApiError: FakeApiError,
  api: {
    openWeb: (...a: unknown[]) => openWeb(...a),
    recommendations: (...a: unknown[]) => recommendations(...a),
  },
  opensHere: (item: { format: string; open_here?: boolean }) => item.open_here ?? item.format === "article",
}));
const navigate = vi.fn();
vi.mock("../src/lib/router", () => ({
  navigate: (...a: unknown[]) => navigate(...a),
  withParams: (url: URL, params: Record<string, string | null>) => {
    for (const [k, v] of Object.entries(params)) if (v) url.searchParams.set(k, v);
    return url.pathname + url.search;
  },
}));

const { toChips, shownOnce, loadNextUp } = await import("../src/lib/nextUp");
const { openRec } = await import("../src/lib/openRec");
import type { RecItem } from "../src/lib/api";

const item = (over: Partial<RecItem>): RecItem =>
  ({
    id: "lib:a", kind: "library", relation: "explainer", relation_label: "Explainer", format: "article",
    title: "Swaps, explained", url: "https://mint.example/a", content_id: "a", source: "Mint",
    duration_or_read_time: 360, snippet: "", thumbnail: null, published_at: null, why: "", triggers: [],
    score: 1, open_here: true, ...over,
  }) as RecItem;  // prettier-ignore

beforeEach(() => {
  openWeb.mockReset();
  navigate.mockReset();
  recommendations.mockReset();
});

describe("toChips", () => {
  it("maps at most 3 items: library to the reader, web to the source, minutes rounded", () => {
    const chips = toChips(
      [
        item({}),
        item({ id: "web:v", kind: "web", format: "video", content_id: null, url: "https://youtu.be/x", duration_or_read_time: 95 }),
        item({ id: "web:p", kind: "web", format: "podcast", content_id: null, url: "https://pod.example/e", duration_or_read_time: null }),
        item({ id: "lib:z" }),
      ],
      "trader",
      "doc1",
    );
    expect(chips.map((c) => c.id)).toEqual(["lib:a", "web:v", "web:p"]);
    expect(chips[0]!.href).toBe("/read/a?persona=trader&rec=lib%3Aa&from=doc1");
    expect(chips[1]!.href).toBe("https://youtu.be/x");
    expect(chips.map((c) => c.minutes)).toEqual([6, 2, null]);
  });
});

describe("shownOnce", () => {
  it("passes each id once per page", () => {
    const seen = new Set<string>();
    expect(shownOnce(seen, ["a", "b"])).toEqual(["a", "b"]);
    expect(shownOnce(seen, ["b", "c"])).toEqual(["c"]);
  });
});

describe("openRec", () => {
  it("library: navigates to the reader", async () => {
    await openRec(item({}), null, "doc1");
    expect(navigate).toHaveBeenCalledWith("/read/a?rec=lib%3Aa&from=doc1");
  });

  it("web it can open: brings it in and navigates; on failure opens the source", async () => {
    openWeb.mockResolvedValueOnce({ content_id: "new1" });
    await openRec(item({ id: "web:x", kind: "web", content_id: null, url: "https://x.example/a" }), null, "doc1");
    expect(navigate).toHaveBeenCalledWith("/read/new1?rec=web%3Ax&from=doc1");
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    openWeb.mockRejectedValueOnce(new Error("no"));
    await openRec(item({ id: "web:y", kind: "web", content_id: null, url: "https://y.example/a" }), null, "doc1");
    expect(open).toHaveBeenCalledWith("https://y.example/a", "_blank", "noopener,noreferrer");
  });

  it("web it can't open: the source in a new tab", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    await openRec(item({ id: "web:v", kind: "web", format: "video", content_id: null, url: "https://youtu.be/x", open_here: false }), null, "d");
    expect(openWeb).not.toHaveBeenCalled();
    expect(open).toHaveBeenCalledWith("https://youtu.be/x", "_blank", "noopener,noreferrer");
  });
});

describe("loadNextUp", () => {
  it("asks for the article basis and polls while pending", async () => {
    vi.useFakeTimers();
    recommendations
      .mockResolvedValueOnce({ items: [item({})], pending: true })
      .mockResolvedValueOnce({ items: [item({}), item({ id: "web:v" })], pending: false });
    const got: number[] = [];
    const stop = loadNextUp("doc1", "newcomer", (items) => got.push(items.length));
    await vi.advanceTimersByTimeAsync(0);
    expect(recommendations.mock.calls[0]!.slice(0, 3)).toEqual(["doc1", "newcomer", null]);
    expect(recommendations.mock.calls[0]![4]).toBe("article");
    await vi.advanceTimersByTimeAsync(1500);
    expect(got).toEqual([1, 2]);
    stop();
    vi.useRealTimers();
  });
});

describe("loadNextUp while the page is analysed (decision 68 B)", () => {
  it("asks once more after a 409, and not again after a second one", async () => {
    vi.useFakeTimers();
    recommendations
      .mockRejectedValueOnce(new FakeApiError("pending", 409))
      .mockResolvedValueOnce({ items: [item({})], pending: false });
    const got: number[] = [];
    const stop = loadNextUp("doc9", null, (items) => got.push(items.length));
    await vi.advanceTimersByTimeAsync(0);
    expect(got).toEqual([]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(got).toEqual([1]);
    recommendations.mockReset();
    recommendations.mockRejectedValue(new FakeApiError("pending", 409));
    const stop2 = loadNextUp("doc10", null, () => undefined);
    await vi.advanceTimersByTimeAsync(10000);
    expect(recommendations).toHaveBeenCalledTimes(2); // the first try and one retry
    stop();
    stop2();
    vi.useRealTimers();
  });
});

describe("useNextUp", () => {
  it("asks only once the notes are ready", async () => {
    const { act } = await import("react");
    const { createRoot } = await import("react-dom/client");
    const { createElement } = await import("react");
    const { useNextUp } = await import("../src/hooks/useNextUp");
    recommendations.mockReset();
    recommendations.mockResolvedValue({ items: [item({})], pending: false });
    let refs: ReturnType<typeof useNextUp> | null = null;
    let arrivals = 0;
    function Probe({ ready }: { ready: boolean }) {
      refs = useNextUp("doc11", null, ready, () => arrivals++);
      return null;
    }
    const host = document.createElement("div");
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    await act(async () => root.render(createElement(Probe, { ready: false })));
    expect(recommendations).not.toHaveBeenCalled();
    await act(async () => root.render(createElement(Probe, { ready: true })));
    expect(recommendations).toHaveBeenCalledTimes(1);
    expect(arrivals).toBe(1); // decision 68: an open card is told chips arrived
    expect(refs!.chips.current.map((c) => c.id)).toEqual(["lib:a"]);
    await act(async () => root.unmount());
  });
});
