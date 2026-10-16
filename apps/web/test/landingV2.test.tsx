// @vitest-environment jsdom
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// /v2 must never sign in or start a demo (docs/plans/landing-v2.md R3): every auth entry is a spy.
const auth = vi.hoisted(() => ({
  signInWithGoogle: vi.fn(),
  startDemo: vi.fn(),
}));
vi.mock("../src/lib/auth", async (original) => ({ ...(await original<object>()), ...auth }));

import LandingRoute from "../src/pages/LandingPage";
import LandingV2 from "../src/landing/v2/LandingV2";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let reduced = false;
let root: Root | null = null;
let host: HTMLDivElement;
const fetchSpy = vi.fn();
const animate = vi.fn();

beforeEach(() => {
  reduced = false;
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("reduced-motion") ? reduced : query.includes("min-width: 1024px"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  vi.stubGlobal("fetch", fetchSpy);
  Element.prototype.animate = animate as unknown as Element["animate"];
  window.history.replaceState(null, "", "/v2");
  host = document.createElement("div");
  document.body.append(host);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  host.remove();
  vi.unstubAllGlobals();
  fetchSpy.mockReset();
  animate.mockReset();
  auth.signInWithGoogle.mockReset();
  auth.startDemo.mockReset();
});

async function render(node: React.ReactNode) {
  root = createRoot(host);
  await act(async () => root!.render(node));
  // The lazy /v2 chunk: let it resolve, then render again.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

const text = () => host.textContent ?? "";

// Strings from the teammate's prompt, verbatim (the plan's Appendix).
const COPY = [
  "Reshape something",
  "Same content. Your shape.",
  "Every article, video, podcast, and paper comes in one fixed shape. Reshape it for how you're reading right now. Every sentence traces back to the original.",
  "Reshape an article",
  "Sign in with Google",
  "The demo needs no account, and ending it deletes what it recorded.",
  "Pick your length. Shorter for a quick read, full for depth. Same source either way.",
  "Pick your level. Simpler or more technical, built from the same sentences.",
  "Pick your format. Read, listen, watch, or scan. Every version comes from the same source.",
  "Every reshaped sentence is checked against the original. [X/Y] reshaped passages traced correctly in our tests.",
  "Works on:",
  "From The Economic Times · reshaped from the original · every line traces to its source",
  "Try it on any article",
  "Same Economic Times article, three shapes: full read, 2-minute version, and audio. Each line links back to the original.",
  "Reshape in your browser.",
  "Open any page and pick a shape.",
  "Videos and podcasts, your shape.",
  "Paste a YouTube video or podcast link. Get the transcript reshaped by length or level, with each line pointing to the moment it came from. Tap any line to play that moment.",
  "One shape doesn't fit every reader.",
  "Too long for this moment",
  "Too dense for this reader",
  "Wrong format for this place",
  "Same content. No two readers need it in the same shape.",
  "It learns your shapes.",
  "The app remembers the lengths, levels, and formats you pick, so next time it starts where you like it.",
  "Pick a shape",
  "Reshape it, sentence by sentence",
  "Check each line against the source",
  "Save the shapes you like",
  "Read, listen, watch, or scan.",
  "Every sentence traces back to the original.",
  "reshaped lines traced to source",
  "changed-meaning lines caught",
  "shapes kept the original's facts",
  "Your next piece, in your shape.",
];

describe("/v2 concept landing", () => {
  it("shows the prompt's copy, word for word", async () => {
    await render(<LandingV2 />);
    const flat = text().replace(/\s+/g, " ");
    for (const s of COPY) expect(flat, s).toContain(s);
    for (const chip of ["Articles", "Papers", "Lectures", "Videos", "Podcasts", "Documentaries", "Any link", "Chrome extension"]) {
      expect([...host.querySelectorAll(".lp-chip")].map((c) => c.textContent)).toContain(chip);
    }
    expect(text()).not.toMatch(/Try the demo|Read anything|What the author is saying|Margo learns/);
  });

  it("is noindex and titled while mounted, and leaves the head as it was", async () => {
    document.title = "Gloss";
    await render(<LandingV2 />);
    expect(document.head.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("noindex, nofollow");
    expect(document.title).toBe("Gloss · Same content. Your shape.");
    await act(async () => root!.unmount());
    root = null;
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull();
    expect(document.title).toBe("Gloss");
  });

  it("every button and inert link does nothing: no sign-in, no demo, no request, no navigation", async () => {
    await render(<LandingV2 />);
    const targets = [...host.querySelectorAll<HTMLElement>("button, span.btn, .lp2-inert-link")];
    expect(targets.length).toBeGreaterThan(10);
    await act(async () => {
      for (const t of targets) t.click();
    });
    expect(auth.signInWithGoogle).not.toHaveBeenCalled();
    expect(auth.startDemo).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/v2");
  });

  it("the router sends /v2 to the concept and anything else to the current landing", async () => {
    await render(<LandingRoute url={new URL("http://localhost/v2")} />);
    expect(text()).toContain("Same content. Your shape.");
  });

  it("/ still renders the current landing, unchanged", async () => {
    window.history.replaceState(null, "", "/");
    await render(<LandingRoute url={new URL("http://localhost/")} />);
    expect(text()).toContain("Consume anything.");
    expect(text()).toContain("Try the demo");
    expect(text()).not.toContain("Your shape");
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("/v2 reshape demo", () => {
  const line = (id: string) => host.querySelector<HTMLButtonElement>(`.lp2-shape__item:nth-child(${id}) .lp2-line`)!;
  const marked = () => [...host.querySelectorAll(".lp2-clause--on")].map((e) => e.getAttribute("data-clause"));

  it("focus marks a line's clause in the original, blur clears it, a click pins it", async () => {
    await render(<LandingV2 />);
    await act(async () => line("2").focus());
    expect(marked()).toEqual(["c2"]);
    await act(async () => line("2").blur());
    expect(marked()).toEqual([]);
    await act(async () => line("3").click());
    expect(line("3").getAttribute("aria-pressed")).toBe("true");
    expect(marked()).toEqual(["c3"]);
    await act(async () => line("3").click());
    expect(line("3").getAttribute("aria-pressed")).toBe("false");
  });

  it("each line names its source tag", async () => {
    await render(<LandingV2 />);
    for (const b of host.querySelectorAll(".lp2-line")) expect(b.textContent).toMatch(/^¶5 s1/);
  });

  const choose = async (label: string) => {
    const option = [...host.querySelectorAll<HTMLButtonElement>(".lp2-controls button")].find((b) => b.textContent === label)!;
    await act(async () => option.click());
  };

  it("a change animates the lines (lines that join fade in)", async () => {
    await render(<LandingV2 />);
    await choose("2 min");
    await choose("Full");
    expect(animate).toHaveBeenCalled();
  });

  it("with reduced motion nothing animates", async () => {
    reduced = true;
    await render(<LandingV2 />);
    await choose("2 min");
    await choose("Full");
    expect(animate).not.toHaveBeenCalled();
  });

  it("arrow keys move each control", async () => {
    await render(<LandingV2 />);
    const tracks = host.querySelectorAll<HTMLElement>(".lp2-controls .segmented__track");
    expect(tracks).toHaveLength(3);
    const checked = (t: HTMLElement) => t.querySelector('[aria-checked="true"]')?.textContent;
    const before = [...tracks].map(checked);
    await act(async () => {
      for (const t of tracks) t.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    const after = [...tracks].map(checked);
    after.forEach((a, i) => expect(a).not.toBe(before[i]));
  });
});

describe("/v2 code stays inert and scoped", () => {
  const dir = resolve(process.cwd(), "src/landing/v2");
  const files = readdirSync(dir);

  it("imports nothing that signs in, calls the API or navigates", () => {
    for (const f of files.filter((f) => /\.tsx?$/.test(f))) {
      // Code only: comments may say what the page doesn't do.
      const src = readFileSync(resolve(dir, f), "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
      expect(src, f).not.toMatch(/lib\/auth|lib\/api|Api["']|navigate/);
    }
  });

  it("every selector in v2.css starts with .lp2", () => {
    const css = readFileSync(resolve(dir, "v2.css"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/@[^{]+\{/g, ""); // at-rule headers (media queries) aren't selectors
    const selectors = [...css.matchAll(/([^{}@]+)\{/g)].map((m) => m[1]!.trim()).filter((s) => s && !s.startsWith("("));
    expect(selectors.length).toBeGreaterThan(5);
    for (const group of selectors) for (const s of group.split(",")) expect(s.trim(), s).toMatch(/^\.lp2/);
  });
});
