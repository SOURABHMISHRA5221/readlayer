// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token", signOutUser: async () => undefined }));
vi.mock("../src/lib/recEvents", () => ({ queueRecEvent: () => undefined }));

import ForYouTab from "../src/components/library/ForYouTab";
import type { FeedItem } from "../src/lib/feedApi";
import { ARTICLE_BASIS, READINESS_BASIS, readinessLine } from "../src/lib/readiness";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Readiness on For you (decision 60, docs/plans/readiness.md): one line from the reader's own map.

describe("readinessLine", () => {
  it("says each level in its exact words", () => {
    expect(readinessLine({ readiness: "familiar" })).toBe("Mostly familiar");
    expect(readinessLine({ readiness: "ready" })).toBe("Ready for you");
    expect(readinessLine({ readiness: "stretch", read_first: ["Bond", "Bond yield"] })).toBe(
      "A stretch: read up on Bond and Bond yield first",
    );
    expect(readinessLine({ readiness: "stretch", read_first: ["Bond"] })).toBe("A stretch: read up on Bond first");
    expect(readinessLine({ readiness: "stretch", read_first: [] })).toBe("A stretch: many new ideas at once");
    expect(readinessLine({ readiness: "stretch" })).toBe("A stretch: many new ideas at once");
  });

  it("says nothing when the item names no idea or the API is older", () => {
    expect(readinessLine({ readiness: null })).toBeNull();
    expect(readinessLine({})).toBeNull();
  });
});

let root: Root;
let host: HTMLDivElement;

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
});

function feedItem(over: Partial<FeedItem>): FeedItem {
  return {
    id: "x", topic: "economics", topic_label: "Economics", format: "article", title: "T", url: "https://news.example/a",
    source: "news.example", snippet: "", thumbnail: null, duration_or_read_time: 300, published_at: null,
    new_concepts: [], goal: null, why: "", score: 1, open_here: true, ...over,
  }; // prettier-ignore
}

async function mountFeed(items: FeedItem[]) {
  const feed = { topics: ["economics"], items, pending: false, snapshot: false, prepared_at: null, country: "IN" };
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(feed), { status: 200 }));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<ForYouTab persona={null} />));
  await act(async () => new Promise((r) => setTimeout(r, 0)));
}

const row = (title: string) =>
  [...host.querySelectorAll("article.row")].find((r) => r.querySelector(".row__title")?.textContent?.includes(title))!;

describe("For you rows", () => {
  it("show the goal first, then readiness, in one why line, and nothing in the meta line", async () => {
    await mountFeed([
      feedItem({ id: "a", title: "Yield curves", goal: "Understand bonds", readiness: "stretch", read_first: ["Bond"], new_concepts: ["Yield curve"] }),
      feedItem({ id: "b", title: "Rates today", readiness: "ready", new_concepts: ["Interest rate"] }),
    ]);
    const whys = row("Yield curves").querySelectorAll(".row__why");
    expect(whys).toHaveLength(1);
    expect(whys[0].textContent).toBe("Picked for your goal Understand bonds · A stretch: read up on Bond first");
    expect(whys[0].querySelector(`[title="${READINESS_BASIS}"]`)?.textContent).toBe("A stretch: read up on Bond first");
    expect(row("Rates today").querySelector(".row__why")?.textContent).toBe("Ready for you");
    for (const meta of host.querySelectorAll(".row__meta")) expect(meta.textContent).not.toMatch(/stretch|Ready|familiar/i);
  });

  it("say where the line comes from: the stored article's ideas or the title (decision 65)", async () => {
    await mountFeed([
      feedItem({ id: "e", title: "Stored", readiness: "ready", readiness_basis: "article" }),
      feedItem({ id: "f", title: "Titled", readiness: "familiar", readiness_basis: "title" }),
      feedItem({ id: "g", title: "Older API", readiness: "ready" }),
    ]);
    const basis = (t: string) => row(t).querySelector(".row__why span")?.getAttribute("title");
    expect(basis("Stored")).toBe(ARTICLE_BASIS);
    expect(ARTICLE_BASIS).toBe("Based on the main ideas in the article");
    expect(basis("Titled")).toBe(READINESS_BASIS);
    expect(basis("Older API")).toBe(READINESS_BASIS);
  });

  it("show nothing new when the API leaves the fields out or names no idea", async () => {
    await mountFeed([feedItem({ id: "c", title: "Old API" }), feedItem({ id: "d", title: "No ideas", readiness: null })]);
    expect(row("Old API").querySelector(".row__why")).toBeNull();
    expect(row("No ideas").querySelector(".row__why")).toBeNull();
  });
});
