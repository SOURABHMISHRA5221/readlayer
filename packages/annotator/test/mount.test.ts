import { afterEach, describe, expect, it, vi } from "vitest";

import { CARD_LABEL, mount, type AnnotatorEvent, type CardAnnotation } from "../src/index";

const HTML = `
  <article id="root">
    <p data-rl-paragraph="p0">The <em>repo</em> rate rose while the yield curve inverted.</p>
    <p data-rl-paragraph="p1">Bond   markets watched the yield curve closely.</p>
  </article>
  <button id="after">after</button>`;

function annotation(id: string, exact: string, paragraph_id: string, extra: Partial<CardAnnotation> = {}): CardAnnotation {
  return {
    id,
    kind: "span",
    anchor: { exact, prefix: "", suffix: "" },
    paragraph_id,
    score: 0.7,
    concept_id: `c_${id}`,
    label: exact,
    definition: `${exact} defined.`,
    prerequisites: ["Bond", "Interest rate"],
    ...extra,
  };
}

function setup(annotations: CardAnnotation[]) {
  document.body.innerHTML = HTML;
  const root = document.getElementById("root") as HTMLElement;
  const events: AnnotatorEvent[] = [];
  const before = root.textContent;
  const mounted = mount(root, annotations, { onEvent: (e) => events.push(e) });
  return { root, events, before, mounted };
}

const card = () => document.querySelector<HTMLElement>(".rl-card")!;
const key = (el: Element, k: string, shift = false) =>
  el.dispatchEvent(new KeyboardEvent("keydown", { key: k, shiftKey: shift, bubbles: true }));

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("mount", () => {
  it("marks spans inside their paragraph without changing the text", () => {
    const { root, before, mounted } = setup([
      annotation("yc", "yield curve", "p1"),
      annotation("repo", "repo rate", "p0"), // crosses the <em>
      annotation("bm", "Bond markets", "p1"), // whitespace fallback
      annotation("missing", "quantitative easing", "p0"),
    ]);
    expect(root.textContent).toBe(before);
    expect(mounted.resolved).toEqual(["yc", "repo", "bm"]);
    expect(mounted.unresolved).toEqual(["missing"]);
    const yc = root.querySelector('[data-rl-id="yc"]')!;
    expect(yc.closest("p")!.getAttribute("data-rl-paragraph")).toBe("p1");
    expect(root.querySelectorAll('[data-rl-id="repo"]').length).toBe(2);
  });

  it("skips an annotation that overlaps an earlier one", () => {
    const { mounted } = setup([annotation("a", "yield curve", "p0"), annotation("b", "curve inverted", "p0")]);
    expect(mounted.unresolved).toEqual(["b"]);
  });

  it("destroy restores the original DOM", () => {
    const { root, mounted } = setup([annotation("yc", "yield curve", "p0")]);
    const original = HTML.replace(/\s+/g, " ");
    mounted.destroy();
    expect(root.querySelector(".rl-mark")).toBeNull();
    expect(document.querySelector(".rl-card")).toBeNull();
    expect(root.querySelector("p")!.childNodes.length).toBe(3); // "The ", <em>, rest
    expect(document.body.innerHTML.replace(/\s+/g, " ")).toBe(original);
  });

  it("is keyboard operable with ARIA state", () => {
    const { root, events } = setup([annotation("yc", "yield curve", "p0", { debug: null })]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    expect(mark.getAttribute("role")).toBe("button");
    expect(mark.tabIndex).toBe(0);
    expect(mark.getAttribute("aria-controls")).toBe(card().id);

    mark.focus();
    key(mark, "Enter");
    expect(mark.getAttribute("aria-expanded")).toBe("true");
    expect(card().hidden).toBe(false);
    expect(card().getAttribute("role")).toBe("dialog");
    expect(document.activeElement).toBe(card());
    expect(card().textContent).toContain(CARD_LABEL);
    expect(card().textContent).toContain("Before this: Bond · Interest rate");
    expect(card().querySelector(".rl-card__debug")!.hasAttribute("hidden")).toBe(true);
    expect(events.map((e) => e.type)).toEqual(["explain_opened"]);

    key(card(), "Escape");
    expect(card().hidden).toBe(true);
    expect(mark.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(mark);
  });

  it("buttons log events and Tab past the last one moves on", () => {
    const { root, events } = setup([annotation("yc", "yield curve", "p0")]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    key(mark, " ");
    const [knew, helpful] = Array.from(card().querySelectorAll("button"));
    knew!.click();
    helpful!.click();
    expect(events.map((e) => e.type)).toEqual(["explain_opened", "knew_this", "explain_helpful"]);
    expect(events[1]).toMatchObject({ annotation_id: "yc", concept_id: "c_yc" });
    expect(knew!.getAttribute("aria-pressed")).toBe("true");
    expect(mark.classList.contains("rl-mark--known")).toBe(true);

    helpful!.focus();
    key(helpful!, "Tab");
    expect(card().hidden).toBe(true);
    expect(document.activeElement!.id).toBe("after");
  });

  it("click toggles a pinned card and shows debug when present", () => {
    const debug = { p_know: 0.27, salience: 0.9, span_score: 0.66, domain: "finance", base_difficulty: 1 };
    const { root } = setup([annotation("yc", "yield curve", "p0", { debug })]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    mark.click();
    expect(card().hidden).toBe(false);
    expect(card().querySelector(".rl-card__debug")!.textContent).toContain("finance");
    mark.click();
    expect(card().hidden).toBe(true);
  });

  it("hover opens after a delay and closes after leaving", () => {
    vi.useFakeTimers();
    const { root } = setup([annotation("yc", "yield curve", "p0")]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    mark.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
    expect(card().hidden).toBe(true);
    vi.advanceTimersByTime(200);
    expect(card().hidden).toBe(false);
    mark.dispatchEvent(new MouseEvent("pointerout", { bubbles: true, relatedTarget: document.body }));
    vi.advanceTimersByTime(300);
    expect(card().hidden).toBe(true);
  });

  it("renders annotation text as text, never HTML", () => {
    const { root } = setup([annotation("yc", "yield curve", "p0", { definition: "<img src=x onerror=alert(1)>" })]);
    root.querySelector<HTMLElement>(".rl-mark")!.click();
    expect(card().querySelector("img")).toBeNull();
  });
});
