import { afterEach, describe, expect, it, vi } from "vitest";

import { connectExtension, EXTENSION_ID, extensionState } from "../src/lib/extension";

type Reply = (response: unknown) => void;

function fakeChrome(handler: (id: string, message: { type: string }, reply: Reply) => void, lastError?: object) {
  const runtime = {
    lastError,
    sendMessage: (id: string, message: { type: string }, reply: Reply) => handler(id, message, reply),
  };
  vi.stubGlobal("chrome", { runtime });
}

afterEach(() => vi.unstubAllGlobals());

describe("lib/extension", () => {
  it("is missing when no extension lists this origin", async () => {
    expect(await extensionState()).toBe("missing");
  });
  it("is missing when Chrome reports the id unknown", async () => {
    fakeChrome((_id, _m, reply) => reply(undefined), { message: "Could not establish connection" });
    expect(await extensionState()).toBe("missing");
  });
  it("reports connected or not from the ping, sent to our id only", async () => {
    const seen: string[] = [];
    fakeChrome((id, m, reply) => {
      seen.push(id);
      reply(m.type === "ping" ? { ok: true, connected: true } : null);
    });
    expect(await extensionState()).toBe("connected");
    expect(seen).toEqual([EXTENSION_ID]);
  });
  it("sends the session to connect and reads the answer", async () => {
    let sent: unknown = null;
    fakeChrome((_id, m, reply) => {
      sent = m;
      reply({ ok: true });
    });
    const ok = await connectExtension({ idToken: "t", refreshToken: "r", expiresAt: 1, persona: "trader" });
    expect(ok).toBe(true);
    expect(sent).toEqual({ type: "connect", idToken: "t", refreshToken: "r", expiresAt: 1, persona: "trader" });
  });
});
