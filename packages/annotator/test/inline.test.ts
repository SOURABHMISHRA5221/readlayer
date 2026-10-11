import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAnnotator, type CardAnnotation, type Explanation } from "../src/index";

// Decision 46: a landing demo keeps one note open inside its own box.
const HTML = `<div id="root"><p data-rl-paragraph="p0">The repo rate rose while the yield curve inverted.</p><div id="host"></div></div><button id="after">After</button>`;

function span(id: string, exact: string): CardAnnotation {
  return {
    id, kind: "span", anchor: { exact, prefix: "", suffix: "" }, paragraph_id: "p0", score: 0.7,
    concept_id: `c_${id}`, label: exact, definition: `${exact} defined.`, domain: "finance", prerequisites: [],
  };  // prettier-ignore
}

const verified = (id: string): Explanation => ({
  id: `x-${id}`, kind: "verified", background: `Background for ${id}.`, author_says: "The author says so.",
  band: "unaware", can_simpler: false, can_deeper: false,
});  // prettier-ignore

const tick = () => new Promise((r) => setTimeout(r, 0));
const card = () => document.querySelector<HTMLElement>(".rl-card")!;

async function setup(extra: Parameters<typeof createAnnotator>[1] = {}) {
  document.body.innerHTML = HTML;
  const root = document.getElementById("root")!;
  const host = document.getElementById("host")!;
  const a = createAnnotator(root, {
    inline: host,
    actions: "demo",
    loadExplanation: async (x) => verified(x.id),
    ...extra,
  });
  await a.update([span("repo", "repo rate"), span("yc", "yield curve")]);
  return { a, root, host };
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("inline card host", () => {
  it("renders in the host as a group at a narrow width, with no scrim and no scroll", async () => {
    // A phone width: without inline, this would be a bottom sheet with a scrim.
    window.matchMedia = ((q: string) =>
      ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList);
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const { a, host } = await setup();
    a.open("repo");
    await tick();
    expect(host.contains(card())).toBe(true);
    expect(card().dataset.mode).toBe("inline");
    expect(card().getAttribute("role")).toBe("group");
    expect(card().hidden).toBe(false);
    expect(document.querySelector(".rl-scrim")).toBeNull();
    expect(scroll).not.toHaveBeenCalled();
    a.destroy();
  });

  it("stays hidden until the explanation settles, then reports ready", async () => {
    let resolve: (e: Explanation) => void = () => undefined;
    const ready: string[] = [];
    const { a } = await setup({
      loadExplanation: () => new Promise((r) => (resolve = r)),
      onCardReady: (id) => ready.push(id),
    });
    a.open("repo");
    expect(card().hidden).toBe(true);
    resolve(verified("repo"));
    await tick();
    expect(card().hidden).toBe(false);
    expect(card().textContent).toContain("Background for repo.");
    expect(ready).toEqual(["repo"]);
    a.destroy();
  });

  it("a host open is quiet; a reader's tap announces", async () => {
    const { a, root } = await setup();
    a.open("repo");
    await tick();
    expect(card().querySelector('[role="status"]')).toBeNull();
    root.querySelector<HTMLElement>('[data-rl-id="yc"]')!.click();
    await tick();
    expect(card().querySelector('[role="status"]')).not.toBeNull();
    a.destroy();
  });

  it("outside clicks, scroll, Escape and its own mark leave it open; Escape returns focus to the mark", async () => {
    const { a, root } = await setup();
    a.open("repo");
    await tick();
    document.getElementById("after")!.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    window.dispatchEvent(new Event("scroll"));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    const mark = root.querySelector<HTMLElement>('[data-rl-id="repo"]')!;
    mark.click();
    expect(card().hidden).toBe(false);
    card().dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(card().hidden).toBe(false);
    expect(document.activeElement).toBe(mark);
    a.destroy();
  });

  it("hovering another mark doesn't swap it; tapping does", async () => {
    vi.useFakeTimers();
    const { a, root } = await setup();
    a.open("repo");
    await vi.runAllTimersAsync();
    const yc = root.querySelector<HTMLElement>('[data-rl-id="yc"]')!;
    yc.dispatchEvent(new PointerEvent("pointerover", { bubbles: true, pointerType: "mouse" }));
    yc.dispatchEvent(new PointerEvent("pointerout", { bubbles: true, pointerType: "mouse" }));
    await vi.runAllTimersAsync();
    expect(card().textContent).toContain("Background for repo.");
    yc.click();
    await vi.runAllTimersAsync();
    expect(card().hidden).toBe(false);
    expect(card().textContent).toContain("Background for yc.");
    vi.useRealTimers();
    a.destroy();
  });

  it("has no focus trap: Tab from the last control is left to the page", async () => {
    const { a } = await setup();
    a.open("repo");
    await tick();
    const button = card().querySelector<HTMLButtonElement>(".rl-card__actions button")!;
    button.focus();
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    button.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(false);
    a.destroy();
  });

  it("has no serious axe violations while open", async () => {
    const { a } = await setup();
    a.open("repo");
    await tick();
    const r = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
    a.destroy();
  });
});
