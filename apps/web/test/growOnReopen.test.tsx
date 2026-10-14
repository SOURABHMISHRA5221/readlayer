// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({
  idToken: async () => "token",
  signOutUser: async () => undefined,
  useIsDemo: () => false,
  useSession: () => ({ status: "signed_out" }),
}));

import { GROW_CAPPED } from "../src/lib/grow";
import { ReaderPage } from "../src/pages/ReaderPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// M9 part 1: a reader's stored page that missed concept growth grows when it is reopened.

const ID = "c0ffee";
const ARTICLE = {
  id: ID, title: "A page outside the map", site: "news.example", url: "https://news.example/a", word_count: 400,
  description: null, author: null, published: null, image: null, domain: null,
  paragraphs: [{ id: "p0", text: "The kharif crop depends on the monsoon." }], status: "ready", media: null, refusal: null,
}; // prettier-ignore
const NOTES = (count: number) => ({ content_id: ID, persona: null, density: "balanced", count, annotations: [] });

type Reply = { status: number; body: unknown };
let root: Root;
let host: HTMLDivElement;
let calls: string[];

function stub(content: unknown, grow: Reply[], notes = NOTES(0)) {
  calls = [];
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addEventListener: () => undefined, removeEventListener: () => undefined }));
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} }); // prettier-ignore
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://localhost");
    const call = `${init?.method ?? "GET"} ${u.pathname}`;
    calls.push(call);
    const json = (r: Reply) => new Response(JSON.stringify(r.body), { status: r.status });
    if (call === `GET /v1/content/${ID}`) return json({ status: 200, body: content });
    if (call === `POST /v1/content/${ID}/grow`) return json(grow.length > 1 ? grow.shift()! : grow[0]!);
    if (call === `POST /v1/content/${ID}/analyse`) return json({ status: 200, body: { content_id: ID, status: "ready" } });
    if (call === `GET /v1/content/${ID}/annotations`) return json({ status: 200, body: notes });
    if (u.pathname.startsWith("/v1/me/saved")) return json({ status: 200, body: [] });
    return json({ status: 200, body: { items: [], pending: false } });
  });
}

async function open() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<ReaderPage id={ID} url={new URL(`http://localhost/read/${ID}`)} />));
}

const count = (call: string) => calls.filter((c) => c === call).length;
const settle = (until: () => boolean) =>
  vi.waitFor(async () => {
    await act(async () => new Promise((r) => setTimeout(r, 5)));
    expect(until()).toBe(true);
  }, { timeout: 3000 });

beforeEach(() => {
  window.scrollTo = () => undefined;
});

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ReaderPage grows a page that missed growth", () => {
  it("asks once, then reloads the notes when it grew", async () => {
    stub({ ...ARTICLE, grow_pending: true }, [{ status: 200, body: { content_id: ID, status: "grown", linked: 3 } }]);
    await open();
    await settle(() => count(`GET /v1/content/${ID}/annotations`) === 2);
    expect(count(`POST /v1/content/${ID}/grow`)).toBe(1);
  });

  it("says so honestly when the caps ran out and there are no notes", async () => {
    stub({ ...ARTICLE, grow_pending: true }, [{ status: 200, body: { content_id: ID, status: "capped", linked: 0 } }]);
    await open();
    await settle(() => host.textContent!.includes(GROW_CAPPED));
    expect(count(`GET /v1/content/${ID}/annotations`)).toBe(1);
  });

  it("does nothing more when there was nothing to grow", async () => {
    stub({ ...ARTICLE, grow_pending: true }, [{ status: 200, body: { content_id: ID, status: "none", linked: 0 } }]);
    await open();
    await settle(() => count(`POST /v1/content/${ID}/grow`) === 1);
    await act(async () => new Promise((r) => setTimeout(r, 20)));
    expect(count(`GET /v1/content/${ID}/annotations`)).toBe(1);
    expect(host.textContent).not.toContain(GROW_CAPPED);
  });

  it("asks again while another request is growing it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    stub({ ...ARTICLE, grow_pending: true }, [
      { status: 202, body: { content_id: ID, status: "growing" } },
      { status: 200, body: { content_id: ID, status: "grown", linked: 1 } },
    ]);
    await open();
    await settle(() => count(`POST /v1/content/${ID}/grow`) === 1);
    await act(async () => vi.advanceTimersByTime(5_100));
    await settle(() => count(`GET /v1/content/${ID}/annotations`) === 2);
    expect(count(`POST /v1/content/${ID}/grow`)).toBe(2);
  });

  it("never asks for a page that doesn't need it", async () => {
    stub({ ...ARTICLE, grow_pending: false }, [{ status: 200, body: {} }]);
    await open();
    await settle(() => count(`GET /v1/content/${ID}/annotations`) === 1);
    await act(async () => new Promise((r) => setTimeout(r, 20)));
    expect(count(`POST /v1/content/${ID}/grow`)).toBe(0);
  });

  it("asks once after analysing the page here (growth may have been capped in phase 2)", async () => {
    stub({ ...ARTICLE, status: "analysing" }, [{ status: 200, body: { content_id: ID, status: "none", linked: 0 } }]);
    await open();
    await settle(() => count(`POST /v1/content/${ID}/grow`) === 1);
  });
});
