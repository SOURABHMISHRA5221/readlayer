// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token", signOutUser: async () => undefined }));

import ForYouTab from "../src/components/library/ForYouTab";
import { countryFromLocale } from "../src/lib/country";
import { FEED_STALE, markFeedStale } from "../src/lib/feedStale";
import { wantsCountry } from "../src/lib/feedView";
import WelcomePage from "../src/pages/WelcomePage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Decision 50: the reader's country (prefilled from the locale, stored on save) and Refresh.

interface Call {
  path: string;
  method: string;
  body: unknown;
}
let calls: Call[] = [];
let root: Root;
let host: HTMLDivElement;

function stubApi(routes: Record<string, unknown>) {
  calls = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname;
    calls.push({ path, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : null });
    const reply = routes[path];
    return new Response(JSON.stringify(typeof reply === "function" ? reply() : (reply ?? {})), { status: 200 });
  });
}

async function settle() {
  await act(async () => new Promise((r) => setTimeout(r, 0)));
}

async function mount(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(node));
  await settle();
}

async function click(el: Element | null | undefined) {
  if (!el) throw new Error("missing element");
  await act(async () => (el as HTMLElement).click());
  await settle();
}

const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === text);
const chip = (text: string) =>
  [...host.querySelectorAll<HTMLLabelElement>("label.chip")].find((l) => l.textContent?.includes(text))?.querySelector("input");

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
});

describe("countryFromLocale", () => {
  it("reads the locale's region only", () => {
    expect(countryFromLocale("en-IN")).toBe("IN");
    expect(countryFromLocale("hi-IN")).toBe("IN");
    expect(countryFromLocale("en-GB")).toBe("GB");
    expect(countryFromLocale("en-US")).toBe("US");
    expect(countryFromLocale("fr-FR")).toBe("other");
    expect(countryFromLocale("en")).toBeNull();
    expect(countryFromLocale("")).toBeNull();
    expect(countryFromLocale("not a locale!")).toBeNull();
  });
});

describe("country on screen 1", () => {
  const PROFILE = {
    summary: { text: "", top_domain: null, moved_up_this_week: 0, learning_paused: false },
    domains: [], thinks_in: [], week: { moved_up: [], trend: [] },
    settings: { density: "balanced", explanation_style: "normal", country: null }, persona: null,
    onboarding: { consented: true, consent_version: "consent-v2", done: false, step: "onboarding", field: "software", interests: ["economics"] },
  }; // prettier-ignore

  it("is prefilled from navigator.language and stored only when Continue saves", async () => {
    vi.stubGlobal("navigator", { ...navigator, language: "en-IN" });
    stubApi({ "/v1/me/profile": PROFILE, "/v1/onboarding": { saved: true, next: "discover" }, "/v1/onboarding/discover": { items: [], pending: false } });
    await mount(<WelcomePage />);
    expect(chip("India")?.checked).toBe(true);
    expect(calls.map((c) => c.path)).toEqual(["/v1/me/profile"]); // nothing stored yet
    await click(chip("Somewhere else"));
    expect(chip("Somewhere else")?.checked).toBe(true);
    await click(button("Continue"));
    const saved = calls.find((c) => c.path === "/v1/onboarding")!.body as Record<string, unknown>;
    expect(saved.country).toBe("other");
    expect(calls.some((c) => c.path === "/v1/me/settings")).toBe(false);
  });

  it("keeps a saved country over the locale", async () => {
    vi.stubGlobal("navigator", { ...navigator, language: "en-GB" });
    stubApi({ "/v1/me/profile": { ...PROFILE, settings: { ...PROFILE.settings, country: "IN" } } });
    await mount(<WelcomePage />);
    expect(chip("India")?.checked).toBe(true);
    expect(chip("United Kingdom")?.checked).toBe(false);
  });
});

describe("For you refresh", () => {
  const FEED = (country: string | null, snapshot = false) => ({
    topics: ["economics"], items: [], pending: false, snapshot, prepared_at: null, country,
  }); // prettier-ignore
  const feeds = () => calls.filter((c) => c.path === "/v1/feed").length;

  it("refetches on rl:feed-stale and on Refresh, and asks for a country when none is set", async () => {
    stubApi({ "/v1/feed": FEED(null) });
    await mount(<ForYouTab persona={null} />);
    expect(feeds()).toBe(1);
    expect(host.textContent).toContain("Add your country for news from where you live");
    expect(host.querySelector<HTMLAnchorElement>('a[href="/profile#prefs-title"]')).not.toBeNull();
    await act(async () => markFeedStale());
    await settle();
    expect(feeds()).toBe(2);
    await click(button("Refresh"));
    expect(feeds()).toBe(3);
    expect(FEED_STALE).toBe("rl:feed-stale");
  });

  it("hides the hint once a country is set, and Refresh on a demo snapshot", async () => {
    stubApi({ "/v1/feed": FEED("IN") });
    await mount(<ForYouTab persona={null} />);
    expect(host.textContent).not.toContain("Add your country");
    expect(button("Refresh")).toBeDefined();
    act(() => root.unmount());
    host.remove();
    stubApi({ "/v1/feed": FEED(null, true) });
    await mount(<ForYouTab persona="newcomer" />);
    expect(button("Refresh")).toBeUndefined();
    expect(wantsCountry({ snapshot: true, country: null })).toBe(false);
    expect(wantsCountry({ snapshot: false, country: undefined })).toBe(false); // an older API
  });
});
