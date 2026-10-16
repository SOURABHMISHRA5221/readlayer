// Decision 67: "Up next" chips at the end of the card (N2) and the analogy frame toggle (A4).
import { afterEach, describe, expect, it } from "vitest";

import { createAnnotator, type CardAnnotation, type Explanation, type NextUpChip } from "../src/index";

const HTML = `<article id="root"><p data-rl-paragraph="p0">The repo rate rose while the yield curve inverted.</p></article>`;

function span(id: string, exact: string): CardAnnotation {
  return {
    id, kind: "span", anchor: { exact, prefix: "", suffix: "" }, paragraph_id: "p0", score: 0.7,
    concept_id: `c_${id}`, label: exact, definition: `${exact} defined.`, domain: "finance", prerequisites: [],
  };  // prettier-ignore
}

const CHIPS: NextUpChip[] = [
  { id: "lib:a", format: "article", title: "Credit default swaps, explained", source: "Mint", href: "/read/a", minutes: 6 },
  { id: "web:v", format: "video", title: "How CDS work", source: "YouTube", href: "https://youtube.com/watch?v=1", minutes: 9 },
  { id: "web:p", format: "podcast", title: "The swap show", source: "Apple Podcasts", href: "https://podcasts.apple.com/e", minutes: null },
];

const framed = (used: "pick" | "for_you", pick: string | null, forYou: string | null): Explanation => ({
  id: `x-${used}`, kind: "verified", background: `Background via ${used}.`, author_says: "The author says so.",
  analogy_domain: used === "pick" ? pick : forYou, frames: { pick, for_you: forYou, used },
});  // prettier-ignore

const card = () => document.querySelector<HTMLElement>(".rl-card")!;
const tick = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  document.body.innerHTML = "";
});

describe("Up next chips in the card", () => {
  it("sit at the end of the scrolling body: format word, title, source, a real link", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const shown: string[][] = [];
    const a = createAnnotator(root, { nextUp: () => CHIPS, onNextUpShown: (ids) => shown.push(ids) });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    const body = card().querySelector(".rl-card__body")!;
    const next = body.lastElementChild as HTMLElement;
    expect(next.classList.contains("rl-card__next")).toBe(true);
    expect(next.hidden).toBe(false);
    expect(next.querySelector(".rl-card__next-label")!.textContent).toBe("Up next");
    const links = Array.from(next.querySelectorAll<HTMLAnchorElement>("a.rl-next"));
    expect(links.map((l) => l.querySelector(".rl-next__verb")!.textContent)).toEqual(["Read", "Watch", "Listen"]);
    expect(links[0]!.getAttribute("href")).toBe("/read/a");
    expect(links[1]!.textContent).toContain("How CDS work");
    expect(links[1]!.textContent).toContain("YouTube");
    expect(shown).toEqual([["lib:a", "web:v", "web:p"]]);
    a.destroy();
  });

  it("a click goes to the host, not the link", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const clicked: string[] = [];
    const a = createAnnotator(root, { nextUp: () => CHIPS, onNextUp: (c) => clicked.push(c.id) });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    const link = card().querySelector<HTMLAnchorElement>("a.rl-next")!;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
    expect(clicked).toEqual(["lib:a"]);
    a.destroy();
  });

  it("no chips, no section; never in demo cards", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const a = createAnnotator(root, { nextUp: () => [] });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    expect(card().querySelector<HTMLElement>(".rl-card__next")!.hidden).toBe(true);
    a.destroy();
    document.body.innerHTML = HTML;
    const d = createAnnotator(document.getElementById("root")!, { nextUp: () => CHIPS, actions: "demo" });
    await d.update([span("yc", "yield curve")]);
    d.open("yc");
    await tick();
    expect(card().querySelector<HTMLElement>(".rl-card__next")!.hidden).toBe(true);
    d.destroy();
  });
});

describe("analogy frame toggle", () => {
  it("offers Your pick / For you when they differ, loads the other on click and remembers it", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const calls: string[] = [];
    const a = createAnnotator(root, {
      loadExplanation: async () => framed("pick", "cricket", "finance"),
      loadFramed: async (_x, frame, shift) => {
        calls.push(`${frame}:${shift}`);
        return framed(frame, "cricket", "finance");
      },
    });
    await a.update([span("yc", "yield curve"), span("repo", "repo rate")]);
    a.open("yc");
    await tick();
    const options = () => Array.from(card().querySelectorAll<HTMLButtonElement>(".rl-frame__option"));
    expect(options().map((o) => o.textContent)).toEqual(["Your pick · Cricket", "For you · Finance"]);
    expect(options().map((o) => o.getAttribute("aria-checked"))).toEqual(["true", "false"]);
    expect(card().querySelector(".rl-frame")!.getAttribute("role")).toBe("radiogroup");
    expect(card().querySelector<HTMLElement>(".rl-card__frame")!.hidden).toBe(true);
    options()[1]!.click();
    await tick();
    expect(calls).toEqual(["for_you:0"]);
    expect(card().textContent).toContain("Background via for_you.");
    expect(options().map((o) => o.getAttribute("aria-checked"))).toEqual(["false", "true"]);
    a.open("repo"); // the next card opens in the chosen frame
    await tick();
    expect(calls).toEqual(["for_you:0", "for_you:0"]);
    options()[0]!.click(); // back to the pick: the normal loader
    await tick();
    expect(calls).toHaveLength(2);
    expect(card().textContent).toContain("Background via pick.");
    a.destroy();
  });

  it("arrow keys move the choice", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const calls: string[] = [];
    const a = createAnnotator(root, {
      loadExplanation: async () => framed("pick", "cricket", "finance"),
      loadFramed: async (_x, frame) => {
        calls.push(frame);
        return framed(frame, "cricket", "finance");
      },
    });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    const first = card().querySelector<HTMLButtonElement>(".rl-frame__option")!;
    first.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    await tick();
    expect(calls).toEqual(["for_you"]);
    a.destroy();
  });

  it("no toggle when for-you is missing or the same as the pick; no pick reads No analogy", async () => {
    for (const [pick, forYou, toggle] of [
      ["cricket", null, false],
      ["software", "software", false],
      [null, "finance", true],
    ] as const) {
      document.body.innerHTML = HTML;
      const a = createAnnotator(document.getElementById("root")!, {
        loadExplanation: async () => framed("pick", pick, forYou),
        loadFramed: async (_x, frame) => framed(frame, pick, forYou),
      });
      await a.update([span("yc", "yield curve")]);
      a.open("yc");
      await tick();
      const group = card().querySelector<HTMLElement>(".rl-frame")!;
      expect(group.hidden).toBe(!toggle);
      if (pick === null) {
        expect(Array.from(group.querySelectorAll("button")).map((b) => b.textContent)).toEqual([
          "No analogy",
          "For you · Finance",
        ]);
      }
      a.destroy();
    }
  });

  it("no toggle without loadFramed", async () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(document.getElementById("root")!, {
      loadExplanation: async () => framed("pick", "cricket", "finance"),
    });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    expect(card().querySelector<HTMLElement>(".rl-frame")!.hidden).toBe(true);
    expect(card().querySelector(".rl-card__frame")!.textContent).toBe("Analogy · cricket");
    a.destroy();
  });
});
