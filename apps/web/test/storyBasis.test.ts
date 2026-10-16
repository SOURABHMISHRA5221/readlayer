import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token" }));

import { api } from "../src/lib/api";

// Decision 69 B: the end of the article asks for the story, the card chips for key ideas.

function asked(): string[] {
  const urls: string[] = [];
  vi.stubGlobal("fetch", async (url: string) => {
    urls.push(new URL(url, "http://x").pathname + new URL(url, "http://x").search);
    return new Response(JSON.stringify({ items: [], pending: false }), { status: 200 });
  });
  return urls;
}

afterEach(() => vi.unstubAllGlobals());

describe("recommendations basis", () => {
  it("defaults to the story (the end of the article and the recap)", async () => {
    const urls = asked();
    await api.recommendations("c1", null, null);
    await api.recommendations("c1", "trader", "video");
    expect(urls).toEqual([
      "/v1/content/c1/recommendations?basis=story",
      "/v1/content/c1/recommendations?prefer=video&basis=story&persona=trader",
    ]);
  });

  it("the card chips still ask for key ideas", async () => {
    const urls = asked();
    await api.recommendations("c1", null, null, undefined, "article");
    expect(urls).toEqual(["/v1/content/c1/recommendations?basis=article"]);
  });
});
