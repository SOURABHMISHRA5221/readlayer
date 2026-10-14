// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token", signOutUser: async () => undefined }));
const events: [string, string][] = [];
vi.mock("../src/lib/recEvents", () => ({
  queueRecEvent: (_persona: unknown, type: string, id: string) => events.push([type, id]),
}));

import ForYouTab from "../src/components/library/ForYouTab";
import { Row } from "../src/components/library/Row";
import { UpNext } from "../src/components/UpNext";
import type { RecItem } from "../src/lib/api";
import type { FeedItem } from "../src/lib/feedApi";
import { originalLabel } from "../src/lib/recLabels";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Media follow-up B (decision 55): feed media rows within the caps offer Gloss or the original.

let root: Root;
let host: HTMLDivElement;
let opens = 0;

async function settle() {
  await act(async () => new Promise((r) => setTimeout(r, 0)));
}

async function mount(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(node));
  await settle();
}

/** `/v1/recs/open` never answers, so a row stays "opening" and a second press can be checked. */
function stubApi(routes: Record<string, unknown>) {
  opens = 0;
  vi.stubGlobal("fetch", async (url: string) => {
    const path = new URL(url, "http://localhost").pathname;
    if (path === "/v1/recs/open") {
      opens += 1;
      return new Promise<Response>(() => undefined);
    }
    return new Response(JSON.stringify(routes[path] ?? {}), { status: 200 });
  });
}

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
  events.length = 0;
});

function feedItem(over: Partial<FeedItem>): FeedItem {
  return {
    id: "x", topic: "economics", topic_label: "Economics", format: "article", title: "T", url: "https://news.example/a",
    source: "news.example", snippet: "", thumbnail: null, duration_or_read_time: 300, published_at: null,
    new_concepts: [], goal: null, why: "", score: 1, open_here: true, ...over,
  }; // prettier-ignore
}

const SHORT = feedItem({ id: "v1", format: "video", title: "Rates explained", url: "https://www.youtube.com/watch?v=R8VBRCs2jTU", source: "The Economist", duration_or_read_time: 494 });
const LONG = feedItem({ id: "v2", format: "video", title: "A long lecture", url: "https://www.youtube.com/watch?v=d6fUwCBvVc0", source: "Lectures", duration_or_read_time: 960, open_here: false });
const EPISODE = feedItem({ id: "p1", format: "podcast", title: "Losing money", url: "https://podcasts.apple.com/us/podcast/id1320118593?i=1000791671873", source: "The Indicator", duration_or_read_time: 565 });
const ARTICLE = feedItem({ id: "a1", title: "An article" });
const FEED = { topics: ["economics"], items: [SHORT, LONG, EPISODE, ARTICLE], pending: false, snapshot: false, prepared_at: null, country: "IN" };

const row = (title: string) => [...host.querySelectorAll("article.row")].find((r) => r.querySelector(".row__title")?.textContent?.includes(title))!;
const gloss = (title: string) => row(title).querySelector<HTMLButtonElement>(`button[aria-label="Open in Gloss: ${title}"]`);
const original = (title: string) => row(title).querySelector<HTMLAnchorElement>(".row__choice a");

describe("originalLabel", () => {
  it("names where the original plays, from the URL's host", () => {
    expect(originalLabel({ format: "video", url: SHORT.url })).toBe("Watch on YouTube");
    expect(originalLabel({ format: "podcast", url: EPISODE.url })).toBe("Listen on Apple Podcasts");
    expect(originalLabel({ format: "podcast", url: "https://open.spotify.com/episode/x" })).toBe("Listen on Spotify");
    expect(originalLabel({ format: "podcast", url: "https://www.npr.org/podcasts/x" })).toBe("Listen on npr.org");
    expect(originalLabel({ format: "podcast", url: "not a url" })).toBe("Listen to the original");
    expect(originalLabel({ format: "article", url: ARTICLE.url })).toBe("Open original");
  });
});

describe("Row actions slot", () => {
  it("renders the actions in the meta line, and nothing without them", async () => {
    await mount(
      <>
        <Row source="s" context="c" title="With" href="/x" time="5 min" newCount={0} actions={<button type="button">Act</button>} />
        <Row source="s" context="c" title="Without" href="/y" time="5 min" newCount={0} />
      </>,
    );
    expect(row("With").querySelector(".row__meta button")?.textContent).toBe("Act");
    expect(row("Without").querySelector(".row__choice")).toBeNull();
  });
});

describe("For you media rows", () => {
  it("offer Open in Gloss and the original for a short video, named with the title", async () => {
    stubApi({ "/v1/feed": FEED });
    await mount(<ForYouTab persona={null} />);
    expect(gloss(SHORT.title)?.textContent).toBe("Open in Gloss");
    const link = original(SHORT.title)!;
    expect(link.href).toBe(SHORT.url);
    expect(link.target).toBe("_blank");
    expect(link.rel).toBe("noopener noreferrer");
    expect(link.textContent).toBe(`Watch on YouTube: ${SHORT.title} (opens in a new tab)`);
    expect(link.textContent!.startsWith("Watch on YouTube")).toBe(true); // visible label starts the name
  });

  it("open once in Gloss and stay disabled while opening", async () => {
    stubApi({ "/v1/feed": FEED });
    await mount(<ForYouTab persona={null} />);
    await act(async () => gloss(SHORT.title)!.click());
    await settle();
    expect(opens).toBe(1);
    expect(gloss(SHORT.title)!.disabled).toBe(true);
    await act(async () => gloss(SHORT.title)!.click());
    await settle();
    expect(opens).toBe(1);
    expect(events.filter(([t]) => t === "rec_clicked")).toEqual([["rec_clicked", SHORT.id]]);
    await act(async () => row(SHORT.title).querySelector<HTMLAnchorElement>(".row__title a")!.click());
    await settle();
    expect(opens).toBe(1); // the title doesn't open it a second time either
    expect(events.filter(([t]) => t === "rec_clicked")).toHaveLength(1);
  });

  it("count a click on the original once", async () => {
    stubApi({ "/v1/feed": FEED });
    await mount(<ForYouTab persona={null} />);
    const link = original(SHORT.title)!;
    link.addEventListener("click", (e) => e.preventDefault()); // jsdom: no navigation
    await act(async () => link.click());
    expect(events.filter(([t]) => t === "rec_clicked")).toEqual([["rec_clicked", SHORT.id]]);
    expect(opens).toBe(0);
  });

  it("name the podcast app for an Apple episode", async () => {
    stubApi({ "/v1/feed": FEED });
    await mount(<ForYouTab persona={null} />);
    expect(gloss(EPISODE.title)).not.toBeNull();
    expect(original(EPISODE.title)!.textContent).toContain("Listen on Apple Podcasts");
  });

  it("leave a long video YouTube only, and articles as they were", async () => {
    stubApi({ "/v1/feed": FEED });
    await mount(<ForYouTab persona={null} />);
    expect(gloss(LONG.title)).toBeNull();
    expect(original(LONG.title)).toBeNull();
    const title = row(LONG.title).querySelector<HTMLAnchorElement>(".row__title a")!;
    expect(title.href).toBe(LONG.url);
    expect(title.target).toBe("_blank");
    expect(row(ARTICLE.title).querySelector(".row__choice")).toBeNull();
    expect(row(SHORT.title).querySelector<HTMLAnchorElement>(".row__title a")!.target).toBe(""); // title opens in Gloss
  });
});

describe("Up next", () => {
  it("names the original of a video that opens here", async () => {
    vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
    const item: RecItem = {
      id: "w1", kind: "web", relation: "deeper", relation_label: "Go deeper", format: "video", title: SHORT.title,
      url: SHORT.url, content_id: null, source: "The Economist", duration_or_read_time: 494, snippet: "", thumbnail: null,
      published_at: null, why: "", triggers: [], score: 1, open_here: true,
    }; // prettier-ignore
    stubApi({ "/v1/content/c1/recommendations": { content_id: "c1", persona: null, prefer: null, items: [item], pending: false, web_formats: ["video"] } });
    await mount(<UpNext contentId="c1" persona={null} />);
    const texts = [...host.querySelectorAll(".rec__actions a, .rec__actions button")].map((e) => e.textContent ?? "");
    expect(texts.some((t) => t.startsWith("Open here"))).toBe(true);
    expect(texts.some((t) => t.startsWith("Watch on YouTube"))).toBe(true);
  });
});
