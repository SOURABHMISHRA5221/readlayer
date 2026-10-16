// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token", signOutUser: async () => undefined }));

import type { DiscoverItem } from "../src/lib/onboardingApi";
import { listing, readback } from "../src/lib/readback";
import WelcomePage from "../src/pages/WelcomePage";
import { chosenDomains, EMPTY_ABOUT, frameFor } from "../src/pages/welcome/AboutScreen";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Decision 41: onboarding in 2 screens. The free text lives only in React state.

const PROFILE = (step: string, consented = false) => ({
  summary: { text: "", top_domain: null, moved_up_this_week: 0, learning_paused: false },
  domains: [], thinks_in: [], week: { moved_up: [], trend: [] },
  settings: { density: "balanced", explanation_style: "normal" }, persona: null,
  onboarding: { consented, done: false, step, field: consented ? "software" : null, interests: consented ? ["economics"] : [] },
}); // prettier-ignore

const item = (n: number, format: DiscoverItem["format"] = "article", seconds: number | null = null): DiscoverItem => ({
  id: `feed:${n}`, kind: "web", content_id: null, topic: "economics", topic_label: "Economics",
  format, title: `Story ${n}`, url: `https://x.test/${n}`, source: "x.test", snippet: "",
  thumbnail: null, duration_or_read_time: seconds, published_at: null, know: null, liked: null,
}); // prettier-ignore

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
    return new Response(JSON.stringify(typeof reply === "function" ? reply() : reply ?? {}), { status: 200 });
  });
}

async function mount() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<WelcomePage />));
  await act(async () => new Promise((r) => setTimeout(r, 0)));
}

async function click(el: Element | null | undefined) {
  if (!el) throw new Error("missing element");
  await act(async () => (el as HTMLElement).click());
  await act(async () => new Promise((r) => setTimeout(r, 0)));
}

async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const button = (text: string) => [...host.querySelectorAll("button")].find((b) => b.textContent?.trim() === text);
const chip = (text: string) => [...host.querySelectorAll<HTMLLabelElement>("label.chip")].find((l) => l.textContent?.includes(text))?.querySelector("input");

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
});

describe("readback", () => {
  it("is one deterministic sentence from the answers and frame", () => {
    // Decision 68 K3: taste only, no claim about what the reader knows.
    const input = { liked: ["Economics", "Sports", "Economics"], skipped: ["Law"], frame: "software" };
    const line = readback(input);
    expect(line).toBe("So: more Economics and Sports, less Law. I'll explain new ideas with software analogies.");
    expect(readback(input)).toBe(line);
    expect(readback({ liked: [], skipped: [], frame: null })).toBe(
      "So: a mix of everything you picked. I'll explain new ideas in plain words.",
    );
    expect(listing(["a", "b", "c"])).toBe("a, b and c");
    const mixed = readback({ liked: ["Sports", "Law"], skipped: ["Sports", "Sports"], frame: null });
    expect(mixed.startsWith("So: more Law, less Sports.")).toBe(true);
  });
});

describe("screen 1 helpers", () => {
  it("interests join chosen, mapped and concept domains; the field suggests a frame", () => {
    const about = {
      ...EMPTY_ABOUT,
      topics: ["economics" as const],
      mapped: [{ phrase: "F1", topic: "sports" as const }, { phrase: "x", topic: null }],
      concepts: [{ id: "c_bond", label: "Bond", domain: "finance" as const }],
    };
    expect(chosenDomains(about)).toEqual(["economics", "sports", "finance"]);
    expect(frameFor("software")).toEqual(["software"]);
    expect(frameFor("finance")).toEqual([]);
  });
});

describe("WelcomePage screen 1", () => {
  it("keeps Continue disabled until a field, a format, a topic and consent", async () => {
    stubApi({ "/v1/me/profile": PROFILE("consent") });
    await mount();
    const next = () => button("Continue")!;
    expect(next().disabled).toBe(true);
    await click(chip("Software"));
    await click(chip("Economics"));
    await click(host.querySelector(".consent__check input"));
    expect(next().disabled).toBe(true); // decision 68: read / watch / listen, at least one
    await click(chip("Listen"));
    expect(next().disabled).toBe(false);
    await click(chip("Listen"));
    expect(next().disabled).toBe(true);
    await click(chip("Watch"));
    expect(next().disabled).toBe(false);
    expect(host.querySelector<HTMLAnchorElement>(".consent__link")?.getAttribute("href")).toBe("/privacy");
    expect(calls.map((c) => c.path)).toEqual(["/v1/me/profile"]); // nothing sent before Continue
  });

  it("holds the free text only in React state and sends it only to resolve, after consent", async () => {
    stubApi({
      "/v1/me/profile": PROFILE("consent"),
      "/v1/me/consent": { consented: true },
      "/v1/onboarding/resolve": {
        concepts: [{ id: "c_bond", label: "Bond", domain: "finance" }],
        topics: [{ phrase_index: 0, phrase: "F1", topic: "sports", via: "alias" }],
        unrecognised: ["zz"],
      },
      "/v1/onboarding": { saved: true, next: "discover" },
      "/v1/onboarding/discover": { items: [], pending: false },
    });
    const href = location.href;
    await mount();
    await click(chip("Software"));
    await click(chip("Watch"));
    await click(host.querySelector(".consent__check input"));
    await type(host.querySelector<HTMLInputElement>(".freetext__input")!, "F1, bonds, zz");
    expect(localStorage.length + sessionStorage.length).toBe(0);
    expect(location.href).toBe(href);
    await click(button("Continue"));
    expect(calls.map((c) => c.path)).toEqual(["/v1/me/profile", "/v1/me/consent", "/v1/onboarding/resolve"]);
    expect(calls[1]!.body).toEqual({ version: "consent-v2" });
    expect(host.textContent).toContain("Didn't recognise: zz");
    expect(host.querySelector<HTMLSelectElement>(".matches__select")?.value).toBe("sports");
    await click(button("Continue")); // stays on screen 1 until the second Continue
    const saved = calls.find((c) => c.path === "/v1/onboarding")!.body as Record<string, unknown>;
    // jsdom's navigator.language is en-US: the prefilled country is saved with Continue (decision 50).
    expect(saved).toEqual({ field: "software", interests: ["sports", "finance"], thinks_in: ["software"], country: "US", formats: ["video"] });
    for (const c of calls.filter((c) => c.path !== "/v1/onboarding/resolve")) {
      expect(JSON.stringify(c.body ?? "")).not.toMatch(/F1|bonds|zz/);
    }
    expect(localStorage.length + sessionStorage.length).toBe(0);
    expect(location.href).toBe(href);
  });
});

describe("WelcomePage screen 2", () => {
  it("resumes on screen 2, records picks (no Know this?), shows formats, then reads back after 5 answers", async () => {
    stubApi({
      "/v1/me/profile": PROFILE("discover", true),
      "/v1/onboarding/discover": {
        items: [item(1), item(2, "video", 360), item(3, "podcast", 1440), item(4), item(5)],
        pending: false,
      },
      "/v1/onboarding/pick": { saved: true },
      "/v1/onboarding/finish": { done: true },
    });
    await mount();
    expect(host.querySelector("h1")?.textContent).toBe("Here's what's out there for you");
    expect(calls.find((c) => c.path === "/v1/onboarding/discover")!.body).toEqual({ topics: ["economics"], concepts: [] });
    const cards = [...host.querySelectorAll(".discover-card")];
    expect(cards).toHaveLength(5);
    expect(host.querySelector(".discover-card__know")).toBeNull(); // decision 68: screen 2 is taste only
    expect(cards[1]!.querySelector(".discover-card__meta")?.textContent).toContain("Watch · 6 min");
    expect(cards[2]!.querySelector(".discover-card__meta")?.textContent).toContain("Listen · 24 min");
    const like = (card: Element) => [...card.querySelectorAll("button")].find((b) => b.textContent?.startsWith("I'd"))!;
    expect(cards.map((c) => like(c).textContent)).toEqual([
      "I'd read this", "I'd watch this", "I'd listen to this", "I'd read this", "I'd read this",
    ]); // prettier-ignore
    for (const card of cards.slice(0, 4)) await click(like(card));
    expect(host.querySelector(".welcome__says")?.textContent).not.toMatch(/^So:/);
    await click(like(cards[4]!));
    expect(host.querySelector(".welcome__says")?.textContent).toBe(
      "So: more Economics. I'll explain new ideas with software analogies.",
    );
    expect(calls.filter((c) => c.path === "/v1/onboarding/pick")).toHaveLength(5);
    expect(calls.some((c) => c.path === "/v1/onboarding/know")).toBe(false);
    expect(button("Edit your picks")).toBeTruthy();
    await click(button("Start reading"));
    expect(calls.at(-1)!.path).toBe("/v1/onboarding/finish");
  });
});

describe("decision 48", () => {
  it("shows the consent once more to a reader who agreed to an older version", async () => {
    stubApi({ "/v1/me/profile": { ...PROFILE("onboarding", true), onboarding: { ...PROFILE("onboarding", true).onboarding, step: "onboarding", consent_version: "consent-v1" } } });
    await mount();
    expect(host.querySelector(".consent__check")).not.toBeNull();
    act(() => root.unmount());
    host.remove();
    stubApi({ "/v1/me/profile": { ...PROFILE("onboarding", true), onboarding: { ...PROFILE("onboarding", true).onboarding, step: "onboarding", consent_version: "consent-v2" } } });
    await mount();
    expect(host.querySelector(".consent__check")).toBeNull();
  });

  it("Redo setup: resumes per redo, Cancel ends it, a finished reader outside a redo is sent home", async () => {
    const redoing = { ...PROFILE("done", true), onboarding: { ...PROFILE("done", true).onboarding, done: true, step: "done", redo: "about", consent_version: "consent-v2" } };
    stubApi({ "/v1/me/profile": redoing, "/v1/onboarding/redo/cancel": { redo: null } });
    await mount();
    expect(host.querySelector("h1")?.textContent).toBe("Tell Gloss about you");
    await click(button("Cancel setup"));
    expect(calls.at(-1)!.path).toBe("/v1/onboarding/redo/cancel");
    expect(location.pathname).toBe("/profile");
    act(() => root.unmount());
    host.remove();
    history.replaceState(null, "", "/welcome");
    const finished = { ...PROFILE("done", true), onboarding: { ...PROFILE("done", true).onboarding, done: true, step: "done", redo: null } };
    stubApi({ "/v1/me/profile": finished });
    await mount();
    expect(location.pathname).toBe("/");
  });
});
