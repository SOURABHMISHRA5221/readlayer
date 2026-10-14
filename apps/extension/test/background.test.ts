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
/** Open in Gloss: what POST /v1/recs/open answers, the bodies it got, the tabs opened. */
let openReply: { status: number; body: unknown } | "offline" = { status: 200, body: { content_id: "abc" } };
const openBodies: unknown[] = [];
const opened: string[] = [];

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
  tabs: {
    get: async () => ({ id: 1, url: tabUrl }),
    create: async ({ url }: { url: string }) => void opened.push(url),
  },
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
vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
  const path = new URL(url).pathname;
  calls.push(`fetch ${path}`);
  if (path === "/v1/recs/open") {
    openBodies.push(JSON.parse(String(init?.body)));
    if (openReply === "offline") throw new TypeError("network");
    return new Response(JSON.stringify(openReply.body), { status: openReply.status });
  }
  return new Response(JSON.stringify({ onboarding: { done: profileDone } }), { status: 200 });
});
vi.stubEnv("VITE_API_BASE", "http://api.test");
vi.stubEnv("VITE_WEB_BASE", "https://glossreader.web.app");
vi.stubEnv("VITE_WEB_ORIGINS", "https://glossreader.web.app,https://readlayer.web.app");

const bg = await import("../src/background");

function connect(provider: "anonymous" | "google.com", extra: Record<string, unknown> = {}) {
  store = {
    session: {
      idToken: token(provider), refreshToken: "r", expiresAt: Date.now() + 3_600_000, apiKey: "k", persona: null,
      density: "balanced", ...extra,
    },  // prettier-ignore
  };
}

beforeEach(() => {
  calls.length = 0;
  tabUrl = "https://news.example/story";
  prepared = { ready: true };
  profileDone = true;
  openReply = { status: 200, body: { content_id: "abc" } };
  openBodies.length = 0;
  opened.length = 0;
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

  it("accepts our own origin and remembers it (the web reader opens there, decision 62)", async () => {
    store = {};
    expect(await bg.onExternal(msg, "https://readlayer.web.app")).toEqual({ ok: true });
    expect(store.session).toMatchObject({ refreshToken: "r", persona: null, apiKey: "k", webOrigin: "https://readlayer.web.app" });
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

describe("openVideo (Open in Gloss on YouTube, decision 62)", () => {
  const WATCH = "https://www.youtube.com/watch?v=wajoP_5Cpw8";
  beforeEach(() => {
    tabUrl = "https://www.youtube.com/watch?v=wajoP_5Cpw8&t=42s&si=track&list=PL1";
  });

  it("sends only the canonical watch URL, read from the tab itself, and opens the reader", async () => {
    expect(await bg.openVideo(1)).toEqual({ ok: true });
    expect(openBodies).toEqual([{ url: WATCH }]);
    expect(calls).toEqual(["fetch /v1/recs/open"]);
    expect(opened).toEqual(["https://glossreader.web.app/read/abc"]);
  });

  it("opens on the address the reader connected from", async () => {
    connect("anonymous", { webOrigin: "https://readlayer.web.app" });
    await bg.openVideo(1);
    expect(opened).toEqual(["https://readlayer.web.app/read/abc"]);
  });

  it("ignores a stored origin that isn't one of ours", async () => {
    connect("anonymous", { webOrigin: "https://evil.example" });
    await bg.openVideo(1);
    expect(opened).toEqual(["https://glossreader.web.app/read/abc"]);
  });

  it.each([
    [null, ""],
    ["newcomer", ""],
    ["trader", "?persona=trader"],
  ])("a demo reader as %s gets %s", async (persona, query) => {
    connect("anonymous", { persona });
    await bg.openVideo(1);
    expect(opened).toEqual([`https://glossreader.web.app/read/abc${query}`]);
  });

  it("not a YouTube video page: nothing sent", async () => {
    tabUrl = "https://www.youtube.com/@channel";
    expect(await bg.openVideo(1)).toMatchObject({ ok: false, reason: "not_video" });
    expect(calls).toEqual([]);
  });

  it("signed out: nothing sent", async () => {
    store = {};
    expect(await bg.openVideo(1)).toMatchObject({ ok: false, reason: "signed_out" });
    expect(calls).toEqual([]);
  });

  it("a Google reader who hasn't finished onboarding: nothing opened", async () => {
    connect("google.com");
    profileDone = false;
    expect(await bg.openVideo(1)).toMatchObject({ ok: false, reason: "onboarding" });
    expect(calls).toEqual(["fetch /v1/me/profile"]);
    expect(opened).toEqual([]);
  });

  it.each([
    [
      422,
      "too_long",
      "Too long for Gloss for now: videos up to 10 minutes, podcasts up to 12. Use “Open original” to watch or listen on the publisher's site.",
      "Too long for Gloss for now: videos up to 10 minutes, podcasts up to 12.",
    ],
    [
      422,
      "live",
      "Live streams can't be read in Gloss. Use “Open original” to watch or listen on the publisher's site.",
      "Live streams can't be read in Gloss.",
    ],
    [
      429,
      "media_cap_reached",
      "The demo can open only a few new videos and podcasts a day. Use “Open original” for this one. Sign in with Google for more.",
      "The demo can open only a few new videos and podcasts a day. Sign in with Google for more.",
    ],
    [
      503,
      "media_unavailable",
      "Gloss couldn't look this recording up just now. Use “Open original” to watch or listen on the publisher's site.",
      "Gloss couldn't open this video. Try again, or paste the link in Gloss.",
    ],
  ])("a %i %s shows the API's words without “Open original”", async (status, error, message, shown) => {
    openReply = { status, body: { error, message } };
    expect(await bg.openVideo(1)).toEqual({ ok: false, reason: status >= 500 ? "error" : "refused", message: shown });
    expect(opened).toEqual([]);
  });

  it("offline: a plain retry message", async () => {
    openReply = "offline";
    expect(await bg.openVideo(1)).toEqual({
      ok: false,
      reason: "error",
      message: "Gloss couldn't open this video. Try again, or paste the link in Gloss.",
    });
  });
});

describe("the worker's message listener (who may ask for what)", () => {
  type Listener = (message: unknown, sender: chrome.runtime.MessageSender, reply: (r: unknown) => void) => boolean;
  const listener = () => chromeFake.runtime.onMessage.addListener.mock.calls[0]![0] as Listener;
  const popup = { id: "ext", url: "chrome-extension://ext/popup.html" };

  beforeEach(() => {
    tabUrl = "https://www.youtube.com/watch?v=wajoP_5Cpw8";
  });

  it.each([
    ["a content script", { id: "ext", url: "https://www.youtube.com/watch?v=wajoP_5Cpw8", tab: { id: 1 } }],
    ["another extension page", { id: "ext", url: "chrome-extension://ext/other.html" }],
    ["another extension", { id: "other", url: "chrome-extension://other/popup.html" }],
  ])("open-video from %s is ignored: no request, no tab", async (_who, sender) => {
    const reply = vi.fn();
    expect(listener()({ type: "open-video", tabId: 1 }, sender as chrome.runtime.MessageSender, reply)).toBe(false);
    await new Promise((r) => setTimeout(r, 0));
    expect(reply).not.toHaveBeenCalled();
    expect(calls).toEqual([]);
    expect(opened).toEqual([]);
  });

  it("open-video from the popup opens the video", async () => {
    const result = await new Promise((resolve) => {
      expect(listener()({ type: "open-video", tabId: 1 }, popup as chrome.runtime.MessageSender, resolve)).toBe(true);
    });
    expect(result).toEqual({ ok: true });
    expect(opened).toEqual(["https://glossreader.web.app/read/abc"]);
  });
});

describe("status", () => {
  it("names the web address the popup links to", async () => {
    connect("anonymous", { webOrigin: "https://readlayer.web.app" });
    expect((await bg.status()).web).toBe("https://readlayer.web.app");
    connect("anonymous");
    expect((await bg.status()).web).toBe("https://glossreader.web.app");
    store = {};
    expect((await bg.status()).web).toBe("https://glossreader.web.app");
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
