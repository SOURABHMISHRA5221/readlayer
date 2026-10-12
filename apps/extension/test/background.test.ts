import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The worker with a fake chrome.* (M8 §C2): what each kind of page gets. The order matters:
 * URL refusal before any script, page refusal before any CSS, CSS only for accepted pages.
 */

type Prepared = { mounted: true } | { refused: string } | { noArticle: true } | { ready: true };

const calls: string[] = [];
let tabUrl = "https://news.example/story";
let prepared: Prepared = { ready: true };
let profileDone = true;
let store: Record<string, unknown> = {};

function token(provider: "anonymous" | "google.com", name = "Asha"): string {
  const payload = btoa(JSON.stringify({ name, firebase: { sign_in_provider: provider } }));
  return `h.${payload}.s`;
}

const chromeFake = {
  runtime: {
    id: "ext",
    getURL: (p: string) => `chrome-extension://ext/${p}`,
    onMessage: { addListener: vi.fn() },
    onMessageExternal: { addListener: vi.fn() },
  },
  tabs: { get: async () => ({ id: 1, url: tabUrl }) },
  storage: {
    session: {
      get: async (key: string) => ({ [key]: store[key] }),
      set: async (items: Record<string, unknown>) => void Object.assign(store, items),
      remove: async (key: string) => void delete store[key],
    },
  },
  scripting: {
    executeScript: async (opts: { files?: string[]; func?: unknown }) => {
      if (opts.files) {
        calls.push("inject");
        return [];
      }
      calls.push(calls.includes("css") ? "start" : "prepare");
      return [{ result: prepared }];
    },
    insertCSS: async () => void calls.push("css"),
  },
};

vi.stubGlobal("chrome", chromeFake);
vi.stubGlobal("fetch", async (url: string) => {
  calls.push(`fetch ${new URL(url).pathname}`);
  return new Response(JSON.stringify({ onboarding: { done: profileDone } }), { status: 200 });
});
vi.stubEnv("VITE_API_BASE", "http://api.test");
vi.stubEnv("VITE_WEB_ORIGINS", "https://readlayer.web.app");

const bg = await import("../src/background");

function connect(provider: "anonymous" | "google.com") {
  store = {
    session: {
      idToken: token(provider), refreshToken: "r", expiresAt: Date.now() + 3_600_000, apiKey: "k", persona: null,
      density: "balanced",
    },  // prettier-ignore
  };
}

beforeEach(() => {
  calls.length = 0;
  tabUrl = "https://news.example/story";
  prepared = { ready: true };
  profileDone = true;
  connect("anonymous");
});

describe("readTab", () => {
  it("an accepted page: script, prepare, then CSS, then start", async () => {
    expect(await bg.readTab(1)).toEqual({ ok: true, already: false });
    expect(calls).toEqual(["inject", "prepare", "css", "start"]);
  });

  it.each(["https://mail.google.com/mail/u/0/", "https://netbanking.hdfcbank.com/", "http://192.168.1.1/"])(
    "a refused URL (%s) gets no script at all",
    async (url) => {
      tabUrl = url;
      const result = await bg.readTab(1);
      expect(result).toMatchObject({ ok: false, reason: "refused" });
      expect(calls).toEqual([]);
    },
  );

  it("a page with a password field gets the script's check but no CSS", async () => {
    prepared = { refused: "sensitive_fields" };
    expect(await bg.readTab(1)).toMatchObject({ ok: false, reason: "refused" });
    expect(calls).toEqual(["inject", "prepare"]);
  });

  it("an already mounted page gets nothing new", async () => {
    prepared = { mounted: true };
    expect(await bg.readTab(1)).toEqual({ ok: true, already: true });
    expect(calls).not.toContain("css");
  });

  it("a Google reader who hasn't finished onboarding gets nothing injected", async () => {
    connect("google.com");
    profileDone = false;
    expect(await bg.readTab(1)).toMatchObject({ ok: false, reason: "onboarding" });
    expect(calls).toEqual(["fetch /v1/me/profile"]);
  });

  it("demo readers skip the onboarding check", async () => {
    await bg.readTab(1);
    expect(calls.some((c) => c.includes("/v1/me/profile"))).toBe(false);
  });

  it("signed out: nothing at all", async () => {
    store = {};
    expect(await bg.readTab(1)).toMatchObject({ ok: false, reason: "signed_out" });
    expect(calls).toEqual([]);
  });
});

describe("onExternal (the web app's Connect page)", () => {
  const msg = {
    type: "connect" as const, idToken: token("google.com"), refreshToken: "r", expiresAt: Date.now() + 1000, apiKey: "k",
  };  // prettier-ignore

  it("accepts our own origin", async () => {
    store = {};
    expect(await bg.onExternal(msg, "https://readlayer.web.app")).toEqual({ ok: true });
    expect(store.session).toMatchObject({ refreshToken: "r", persona: null, apiKey: "k" });
  });

  it.each([undefined, "https://evil.example", "https://readlayer.web.app.evil.example"])(
    "refuses origin %s",
    async (origin) => {
      store = {};
      expect(await bg.onExternal(msg, origin)).toEqual({ ok: false, error: "origin" });
      expect(store.session).toBeUndefined();
    },
  );

  it("refuses a persona that isn't one of ours", async () => {
    const bad = { ...msg, persona: "x&debug=1" } as unknown as typeof msg;
    expect(await bg.onExternal(bad, "https://readlayer.web.app")).toEqual({ ok: false, error: "invalid" });
  });

  it("refuses a malformed connect", async () => {
    const bad = { ...msg, refreshToken: 5 } as unknown as typeof msg;
    expect(await bg.onExternal(bad, "https://readlayer.web.app")).toEqual({ ok: false, error: "invalid" });
  });
});

describe("token custody", () => {
  const src = (f: string) => readFileSync(resolve(__dirname, "../src", f), "utf8");
  it("content-side code never touches extension storage or the token", () => {
    for (const f of ["content.ts", "tag.ts", "extract.ts", "toast.ts", "refuse.ts", "redact.ts"]) {
      expect(src(f)).not.toMatch(/chrome\.storage|idToken|refreshToken|Authorization/);
    }
  });
  it("session storage keeps its default trusted-contexts access level", () => {
    for (const f of ["background.ts", "session.ts", "api.ts"]) expect(src(f)).not.toMatch(/setAccessLevel/);
  });
});

describe("extension id", () => {
  it("the manifest's public key gives the id the web app's Connect page uses", async () => {
    const { createHash } = await import("node:crypto");
    const manifest = JSON.parse(readFileSync(resolve(__dirname, "../manifest.base.json"), "utf8")) as { key: string };
    const hex = createHash("sha256").update(Buffer.from(manifest.key, "base64")).digest("hex").slice(0, 32);
    const id = [...hex].map((c) => String.fromCharCode(97 + parseInt(c, 16))).join("");
    const web = readFileSync(resolve(__dirname, "../../web/src/lib/extension.ts"), "utf8");
    expect(web).toContain(`EXTENSION_ID = "${id}"`);
  });
});
