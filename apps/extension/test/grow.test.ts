import { describe, expect, it } from "vitest";

import { finalToast, GROW_CAPPED, growUntilDone, shouldGrow } from "../src/grow";
import type { ApiReply } from "../src/messages";

// M9 part 1: a reader's stored page that missed concept growth grows when it is reopened.

const reply = (status: number, body: unknown): ApiReply => ({ ok: true, status, data: body });

describe("shouldGrow", () => {
  it("asks only for a page the API says missed growth", () => {
    expect(shouldGrow({ grow_pending: true })).toBe(true);
    expect(shouldGrow({ grow_pending: false })).toBe(false);
    expect(shouldGrow({})).toBe(false); // an older API
  });
});

describe("growUntilDone", () => {
  it("asks again while another request is growing the page", async () => {
    const replies = [reply(202, { status: "growing" }), reply(200, { status: "grown", linked: 3 })];
    const asked: string[] = [];
    const done = await growUntilDone("c1", async (op) => {
      asked.push(`${op.op} ${op.id}`);
      return replies.shift()!;
    }, async () => undefined);
    expect(done).toBe("grown");
    expect(asked).toEqual(["grow c1", "grow c1"]);
  });

  it("gives up quietly on an error or after the window", async () => {
    expect(await growUntilDone("c1", async () => ({ ok: false, status: 503, error: "x", message: "m" }), async () => undefined)).toBe("none");
    let now = 0;
    const done = await growUntilDone("c1", async () => reply(202, { status: "growing" }), async () => {
      now += 30_000;
    }, () => now);
    expect(done).toBe("none");
  });
});

describe("finalToast", () => {
  it("is honest about a page whose ideas aren't on the map yet", () => {
    expect(finalToast(3, "grown")).toBe("Notes are ready: 3 on this page.");
    expect(finalToast(0, "capped")).toBe(GROW_CAPPED);
    expect(finalToast(0, "none")).toBe("Nothing new for you on this page.");
    expect(finalToast(0, null)).toBe("Nothing new for you on this page.");
    expect(finalToast(2, "capped")).toBe("Notes are ready: 2 on this page.");
  });
});
