import { describe, expect, it } from "vitest";

import { shouldReload } from "../src/lib/staleChunk";

// Decision 69 E: a tab from before a deploy reloads once when a code file is gone, never in a loop.

function memory(): Pick<Storage, "getItem" | "setItem"> {
  const data = new Map<string, string>();
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

describe("stale code after a deploy", () => {
  it("reloads once, then not again within a minute, then again later", () => {
    const s = memory();
    expect(shouldReload(s, 1_000_000)).toBe(true);
    expect(shouldReload(s, 1_030_000)).toBe(false);
    expect(shouldReload(s, 1_070_000)).toBe(true);
  });

  it("never reloads when storage is blocked", () => {
    const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => undefined };
    expect(shouldReload(blocked, 1)).toBe(false);
    expect(shouldReload(null, 1_000_000)).toBe(false); // nowhere to remember it: no reload
  });
});
