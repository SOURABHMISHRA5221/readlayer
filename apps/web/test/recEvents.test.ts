import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token" }));

import { FLUSH_MS, flushRecEvents, queueRecEvent } from "../src/lib/recEvents";

describe("recommendation signals", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("sends the cards seen together as one request", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ applied: 3, ignored: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    for (const id of ["feed:a", "feed:b", "feed:c"]) queueRecEvent(null, "rec_shown", id);
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(FLUSH_MS);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.events.map((e: { item_id: string }) => e.item_id)).toEqual(["feed:a", "feed:b", "feed:c"]);
    expect(new Set(body.events.map((e: { id: string }) => e.id)).size).toBe(3);
  });

  it("keeps personas apart and flushes on demand", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    queueRecEvent("trader", "rec_shown", "x");
    queueRecEvent("newcomer", "rec_clicked", "y");
    flushRecEvents();
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
    const personas = fetchMock.mock.calls.map((c) => JSON.parse(String((c as unknown as [string, RequestInit])[1].body)).persona);
    expect(personas.sort()).toEqual(["newcomer", "trader"]);
  });
});
