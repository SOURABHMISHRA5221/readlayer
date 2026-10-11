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

const item = (n: number, term?: string): DiscoverItem => ({
  id: `feed:${n}`, kind: "web", content_id: null, topic: "economics", topic_label: "Economics",
  format: "article", title: `Story ${n}`, url: `https://x.test/${n}`, source: "x.test", snippet: "",
  thumbnail: null, duration_or_read_time: null, published_at: null,
  know: term ? { concept_id: `c_${term}`, label: term, known: null } : null, liked: null,
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
    const input = { liked: ["Economics", "Sports", "Economics"], skipped: ["Law"], known: ["Inflation"], unknown: ["Bond"], frame: "software" };
    const line = readback(input);
    expect(line).toBe(
      "So: more Economics and Sports, less Law. You know Inflation, and Bond is new to you, so I'll explain new ideas with software analogies.",
    );
    expect(readback(input)).toBe(line);
    expect(readback({ liked: [], skipped: [], known: [], unknown: ["A", "B"], frame: null })).toBe(
      "So: a mix of everything you picked. A and B are new to you, so I'll explain new ideas in plain words.",
    );
    expect(listing(["a", "b", "c"])).toBe("a, b and c");
    const mixed = readback({ liked: ["Sports", "Law"], skipped: ["Sports", "Sports"], known: [], unknown: [], frame: null });
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
  it("keeps Continue disabled until a field, a topic and consent", async () => {
    stubApi({ "/v1/me/profile": PROFILE("consent") });
    await mount();
    const next = () => button("Continue")!;
    expect(next().disabled).toBe(true);
    await click(chip("Software"));
    await click(chip("Economics"));
    expect(next().disabled).toBe(true);
    await click(host.querySelector(".consent__check input"));
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
    expect(saved).toEqual({ field: "software", interests: ["sports", "finance"], thinks_in: ["software"] });
    for (const c of calls.filter((c) => c.path !== "/v1/onboarding/resolve")) {
      expect(JSON.stringify(c.body ?? "")).not.toMatch(/F1|bonds|zz/);
    }
    expect(localStorage.length + sessionStorage.length).toBe(0);
    expect(location.href).toBe(href);
  });
});

describe("WelcomePage screen 2", () => {
  it("resumes on screen 2, records picks and Know this?, then reads back after 5 answers", async () => {
    stubApi({
      "/v1/me/profile": PROFILE("discover", true),
      "/v1/onboarding/discover": { items: [item(1, "Inflation"), item(2, "Bond"), item(3), item(4)], pending: false },
      "/v1/onboarding/pick": { saved: true },
      "/v1/onboarding/know": { saved: true },
      "/v1/onboarding/finish": { done: true },
    });
    await mount();
    expect(host.querySelector("h1")?.textContent).toBe("Here's what's out there for you");
    expect(calls.find((c) => c.path === "/v1/onboarding/discover")!.body).toEqual({ topics: ["economics"], concepts: [] });
    const cards = [...host.querySelectorAll(".discover-card")];
    expect(cards).toHaveLength(4);
    for (const card of cards.slice(0, 3)) await click([...card.querySelectorAll("button")].find((b) => b.textContent === "I'd read this"));
    await click([...cards[0]!.querySelectorAll("button")].find((b) => b.textContent === "Yes"));
    expect(host.querySelector(".welcome__says")?.textContent).not.toMatch(/^So:/);
    await click([...cards[1]!.querySelectorAll("button")].find((b) => b.textContent === "Not really"));
    expect(host.querySelector(".welcome__says")?.textContent).toBe(
      "So: more Economics. You know Inflation, and Bond is new to you, so I'll explain new ideas with software analogies.",
    );
    expect(calls.filter((c) => c.path === "/v1/onboarding/pick")).toHaveLength(3);
    expect(calls.find((c) => c.path === "/v1/onboarding/know")!.body).toEqual({ concept_id: "c_Inflation", known: true });
    expect(button("Edit your picks")).toBeTruthy();
    await click(button("Start reading"));
    expect(calls.at(-1)!.path).toBe("/v1/onboarding/finish");
  });
});
