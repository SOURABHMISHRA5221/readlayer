import { describe, expect, it } from "vitest";

import type { FeedItem } from "../src/lib/feedApi";
import { MAX_REASKS, pendingNote, reaskDelay, REASK_MS, snapshotNote, visibleItems } from "../src/lib/feedView";

const item = (id: string): FeedItem =>
  ({ id, topic: "health", topic_label: "Health", format: "article", title: id, url: `https://x.test/${id}`, source: "x.test",
     snippet: "", thumbnail: null, duration_or_read_time: null, published_at: null, new_concepts: [], goal: null,
     why: "Health", score: 1 }) as FeedItem;

describe("For you page logic", () => {
  it("asks again every 3 s while searches run, at most 3 times", () => {
    expect([0, 1, 2].map((a) => reaskDelay(true, a))).toEqual([REASK_MS, REASK_MS, REASK_MS]);
    expect(reaskDelay(true, MAX_REASKS)).toBeNull();
    expect(reaskDelay(false, 0)).toBeNull();
  });

  it("changes the waiting line once the re-asks are used up", () => {
    expect(pendingNote(true, 0)).toBe("Still gathering a few picks…");
    expect(pendingNote(true, MAX_REASKS)).toMatch(/still on the way/);
    expect(pendingNote(false, 0)).toBeNull();
  });

  it("tells demo readers the picks were prepared in advance", () => {
    const note = snapshotNote({ snapshot: true, prepared_at: "2026-10-10T17:35:28+00:00" }, () => "10 Oct 2026");
    expect(note).toBe("Picks prepared in advance for this demo (10 Oct 2026), so some may be dated. Sign in with Google for a live feed.");
    expect(snapshotNote({ snapshot: false, prepared_at: null }, () => "")).toBeNull();
  });

  it("hides a card as soon as the reader says not interested", () => {
    expect(visibleItems([item("a"), item("b")], new Set(["a"])).map((i) => i.id)).toEqual(["b"]);
  });
});
