import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token" }));

import { api } from "../src/lib/api";

describe("Read any link", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the pasted URL to /v1/recs/open and nothing else", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ content_id: "abc", new: true, ready: false }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const out = await api.openWeb("https://example.org/story");
    expect(out.content_id).toBe("abc");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toMatch(/\/v1\/recs\/open$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ url: "https://example.org/story" });
  });
});
