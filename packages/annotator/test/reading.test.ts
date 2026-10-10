import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ASK_DONE,
  createAnnotator,
  NO_EXPLANATION_TEXT,
  PARAGRAPH_TITLE,
  renderPreread,
  type AnnotatorEvent,
  type AnyAnnotation,
  type CardAnnotation,
  type ParagraphMarker,
  type PrereadAnnotation,
  type PromptAnnotation,
} from "../src/index";

const HTML = `
  <article id="root">
    <p data-rl-paragraph="p0">The repo rate rose while the yield curve inverted.</p>
    <p data-rl-paragraph="p1">Term premium widened as the central bank sold bonds.</p>
    <p data-rl-paragraph="p2">Nothing in this paragraph is annotated at all.</p>
  </article>`;

const span = (id: string, exact: string, paragraph_id: string): CardAnnotation => ({
  id,
  kind: "span",
  anchor: { exact, prefix: "", suffix: "" },
  paragraph_id,
  score: 0.7,
  concept_id: `c_${id}`,
  label: exact,
  definition: `${exact} defined.`,
  domain: "finance",
  prerequisites: [],
});
const marker = (paragraph_id: string): ParagraphMarker => ({
  id: `para:${paragraph_id}`,
  kind: "paragraph",
  paragraph_id,
  score: 0.8,
  domain: "economics",
});
const prompt = (exact: string, paragraph_id: string): PromptAnnotation => ({
  id: "prompt:d9",
  kind: "prompt",
  anchor: { exact, prefix: "", suffix: "" },
  paragraph_id,
  concept_id: "c_term_premium",
  label: "Term premium",
});

/** Article text the way a reader sees it, minus the annotator's own controls. */
function articleText(root: HTMLElement): string {
  const clone = root.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("[data-rl-ui]").forEach((el) => el.remove());
  return clone.textContent ?? "";
}

class FakeObserver {
  static instance: FakeObserver | null = null;
  readonly targets: Element[] = [];
  constructor(readonly callback: IntersectionObserverCallback) {
    FakeObserver.instance = this;
  }
  observe(el: Element) {
    this.targets.push(el);
  }
  disconnect() {}
  fire(el: Element, visible: boolean) {
    const entry = { target: el, isIntersecting: visible, intersectionRatio: visible ? 1 : 0 };
    this.callback([entry as unknown as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
}

let events: AnnotatorEvent[] = [];
let root: HTMLElement;

async function setup(items: AnyAnnotation[], extra: Parameters<typeof createAnnotator>[1] = {}) {
  document.body.innerHTML = HTML;
  root = document.getElementById("root") as HTMLElement;
  events = [];
  const before = root.textContent;
  const annotator = createAnnotator(root, {
    leaveMs: 0,
    staggerMs: 0,
    hoverDelayMs: 0,
    closeDelayMs: 0,
    onEvent: (e) => events.push(e),
    ...extra,
  });
  const result = await annotator.update(items);
  return { annotator, result, before };
}

const card = () => document.querySelector<HTMLElement>(".rl-card")!;
const btn = (action: string) => card().querySelector<HTMLButtonElement>(`button[data-action="${action}"]`)!;
const key = (el: Element, k: string) =>
  el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
const types = () => events.map((e) => e.type);

function select(node: Node, from: number, to: number, endNode: Node = node) {
  const range = document.createRange();
  range.setStart(node, from);
  range.setEnd(endNode, to);
  const sel = document.getSelection()!;
  sel.removeAllRanges();
  sel.addRange(range);
}

function copy(): { prevented: boolean; data: Record<string, string> } {
  const data: Record<string, string> = {};
  const e = new Event("copy", { bubbles: true, cancelable: true });
  Object.defineProperty(e, "clipboardData", { value: { setData: (t: string, v: string) => (data[t] = v) } });
  const target = document.getSelection()!.getRangeAt(0).startContainer;
  target.dispatchEvent(e);
  return { prevented: e.defaultPrevented, data };
}

beforeEach(() => {
  FakeObserver.instance = null;
  (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = FakeObserver;
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("paragraph markers and the Know this? chip", () => {
  it("never shift anchors or change the article text", async () => {
    const { result, before, annotator } = await setup([
      marker("p0"),
      prompt("Term premium", "p1"),
      span("cb", "central bank", "p1"), // after the chip in the same paragraph
      span("yc", "yield curve", "p0"), // after the marker in the same paragraph
    ]);
    expect(result.resolved).toEqual(["yc", "cb"]);
    expect(result.unresolved).toEqual([]);
    expect(root.querySelector('[data-rl-id="cb"]')!.textContent).toBe("central bank");
    expect(root.querySelector('[data-rl-id="yc"]')!.textContent).toBe("yield curve");
    expect(articleText(root)).toBe(before);
    // A later update still finds anchors with the controls in place.
    await annotator.update([marker("p0"), prompt("Term premium", "p1"), span("bonds", "bonds", "p1")]);
    expect(root.querySelector('[data-rl-id="bonds"]')!.textContent).toBe("bonds");
    annotator.destroy();
    expect(root.textContent).toBe(before);
    expect(root.querySelector("[data-rl-has-marker]")).toBeNull();
  });

  it("a marker opens a paragraph card without Knew this, toggles, and loads by paragraph", async () => {
    const load = vi.fn().mockResolvedValue({ id: "", kind: "definition", background: null, author_says: null });
    await setup([marker("p0")], { loadExplanation: load });
    const m = root.querySelector<HTMLButtonElement>(".rl-pmark")!;
    expect(m.getAttribute("aria-label")).toBe(PARAGRAPH_TITLE);
    m.click();
    expect(card().hidden).toBe(false);
    expect(card().querySelector(".rl-card__title")!.textContent).toBe(PARAGRAPH_TITLE);
    expect(btn("knew_this").hidden).toBe(true);
    expect(load.mock.calls[0]![0]).toMatchObject({ kind: "paragraph", paragraph_id: "p0" });
    await Promise.resolve();
    await Promise.resolve();
    expect(card().textContent).toContain(NO_EXPLANATION_TEXT);
    expect(events[0]).toMatchObject({ type: "explain_opened", paragraph_id: "p0", concept_id: null });
    m.click();
    expect(card().hidden).toBe(true);
    expect(types()).not.toContain("annotation_dismissed"); // no concept: never a dismissal
  });

  it("Escape from a keyboard-opened marker card returns focus to the marker", async () => {
    await setup([marker("p2")]);
    const m = root.querySelector<HTMLButtonElement>(".rl-pmark")!;
    m.focus();
    m.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 0 }));
    expect(document.activeElement).toBe(card());
    key(card(), "Escape");
    expect(card().hidden).toBe(true);
    expect(document.activeElement).toBe(m);
  });

  it("the chip records an answer once and says so; a failed save can be retried", async () => {
    const onAnswer = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    await setup([prompt("Term premium", "p1")], { onAnswer });
    const chip = root.querySelector<HTMLElement>(".rl-ask")!;
    expect(chip.getAttribute("role")).toBe("group");
    expect(chip.getAttribute("aria-label")).toBe("Do you know Term premium?");
    const [yes, no] = Array.from(chip.querySelectorAll("button"));
    no!.click();
    await vi.waitFor(() => expect(chip.textContent).toContain("Try again"));
    expect(yes!.disabled).toBe(false);
    yes!.click();
    await vi.waitFor(() => expect(chip.dataset.state).toBe("done"));
    expect(onAnswer.mock.calls.map((c) => c[1])).toEqual([false, true]);
    expect(onAnswer.mock.calls[1]![0]).toMatchObject({ concept_id: "c_term_premium" });
    expect(chip.querySelector(".rl-ask__status")!.textContent).toBe(ASK_DONE);
    expect(chip.querySelector(".rl-ask__status")!.getAttribute("aria-live")).toBe("polite");
  });
});

describe("pre-read card", () => {
  it("lists steps most basic first: explainer links, else the definition", () => {
    document.body.innerHTML = `<div id="slot"></div>`;
    const item: PrereadAnnotation = {
      id: "preread",
      kind: "preread",
      score: 0.6,
      concept_id: "c_tp",
      label: "term premium",
      steps: [
        { concept_id: "c_bond", label: "Bond", definition: "A loan.", content_id: "abc", title: "Bonds, explained" },
        { concept_id: "c_tp", label: "Term premium", definition: "Extra yield for time." },
      ],
    };
    const onOpen = vi.fn();
    const handle = renderPreread(document.getElementById("slot")!, item, {
      href: (s) => `/read/${s.content_id}`,
      onOpen,
    });
    const section = document.querySelector(".rl-preread")!;
    expect(section.querySelector("h2")!.textContent).toBe("Before you read");
    const steps = section.querySelectorAll("li");
    expect(steps).toHaveLength(2);
    const link = steps[0]!.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("/read/abc");
    expect(link.textContent).toContain("Bond");
    link.click();
    expect(onOpen).toHaveBeenCalled();
    expect(steps[1]!.querySelector("summary")!.textContent).toBe("Term premium");
    expect(steps[1]!.querySelector("details p")!.textContent).toBe("Extra yield for time.");
    handle.destroy();
    expect(document.querySelector(".rl-preread")).toBeNull();
  });
});

describe("annotation_dismissed", () => {
  it("counts a deliberately opened span card closed without an action", async () => {
    await setup([span("yc", "yield curve", "p0")]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    mark.click();
    key(card(), "Escape");
    expect(types()).toEqual(["explain_opened", "annotation_dismissed"]);
    expect(events[1]).toMatchObject({ annotation_id: "yc", concept_id: "c_yc" });
  });

  it("does not count after an action, nor a hover peek, nor a host-driven close", async () => {
    const { annotator } = await setup([span("yc", "yield curve", "p0")]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    mark.click();
    btn("explain_helpful").click();
    key(card(), "Escape");
    vi.useFakeTimers();
    mark.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
    vi.runAllTimers();
    mark.dispatchEvent(new PointerEvent("pointerout", { bubbles: true }));
    vi.runAllTimers();
    vi.useRealTimers();
    annotator.open("yc");
    annotator.close();
    expect(types()).not.toContain("annotation_dismissed");
  });
});

describe("text_searched", () => {
  it("names the concept of a marked term and never sends the text", async () => {
    await setup([span("yc", "yield curve", "p0")]);
    const text = root.querySelector('[data-rl-id="yc"]')!.firstChild!;
    select(text, 0, 5);
    copy();
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: "text_searched", concept_id: "c_yc", paragraph_id: "p0" });
    expect(JSON.stringify(events[0])).not.toContain("yield");
  });

  it("an unmarked paragraph sends the paragraph only; a marked one outside its marks sends nothing", async () => {
    await setup([span("yc", "yield curve", "p0"), marker("p2")]);
    const p2 = root.querySelector('[data-rl-paragraph="p2"]')!;
    select(p2.lastChild!, 0, 7); // "Nothing"
    root.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true }));
    expect(events).toEqual([expect.objectContaining({ type: "text_searched", concept_id: null, paragraph_id: "p2" })]);
    // Again within 10 s: throttled.
    root.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true }));
    expect(events).toHaveLength(1);
    const p0 = root.querySelector('[data-rl-paragraph="p0"]')!;
    select(p0.firstChild!, 0, 8); // "The repo" (p0 has the yield curve mark)
    root.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true }));
    expect(events).toHaveLength(1);
  });

  it("a copy across the chip gives back only the article's words", async () => {
    await setup([prompt("Term premium", "p1")]);
    const p1 = root.querySelector('[data-rl-paragraph="p1"]')!;
    const termText = p1.querySelector(".rl-mark")!.firstChild!;
    const after = p1.lastChild!; // " widened as …"
    select(termText, 0, 8, after);
    const { prevented, data } = copy();
    expect(prevented).toBe(true);
    expect(data["text/plain"]).toBe("Term premium widened");
    expect(data["text/plain"]).not.toContain("Know this");
    expect(events[0]).toMatchObject({ type: "text_searched", concept_id: "c_term_premium" });
  });
});

describe("paragraph_dwell", () => {
  it("emits visible time per paragraph, with its words on the first dwell only", async () => {
    let now = 0;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    await setup([]);
    const io = FakeObserver.instance!;
    const p1 = root.querySelector('[data-rl-paragraph="p1"]')!;
    io.fire(p1, true);
    now = 800;
    io.fire(p1, false); // under a second: nothing
    expect(events).toEqual([]);
    io.fire(p1, true);
    now = 4800;
    io.fire(p1, false);
    io.fire(p1, true);
    now = 7000;
    io.fire(p1, false);
    expect(events.map((e) => [e.type, e.paragraph_id, e.words, e.ms])).toEqual([
      ["paragraph_dwell", "p1", 9, 4000],
      ["paragraph_dwell", "p1", 0, 2200],
    ]);
  });

  it("flush() emits what is in view so far", async () => {
    let now = 0;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const { annotator } = await setup([]);
    const p0 = root.querySelector('[data-rl-paragraph="p0"]')!;
    FakeObserver.instance!.fire(p0, true);
    now = 3000;
    annotator.flush();
    expect(events).toEqual([expect.objectContaining({ type: "paragraph_dwell", paragraph_id: "p0", ms: 3000 })]);
  });
});

describe("accessibility (axe)", () => {
  const serious = (r: axe.AxeResults) =>
    r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id);
  const run = (el: Element) => axe.run(el, { rules: { "color-contrast": { enabled: false } } });

  it("marker, chip, open card and pre-read have no serious violations", async () => {
    await setup([marker("p0"), prompt("Term premium", "p1"), span("yc", "yield curve", "p0")]);
    root.querySelector<HTMLButtonElement>(".rl-pmark")!.click();
    renderPreread(document.body, {
      id: "preread", kind: "preread", score: 0.6, concept_id: "c", label: "x",
      steps: [{ concept_id: "c", label: "Bond", definition: "A loan.", content_id: "a", title: "T" }],
    }, { href: () => "/read/a" });
    expect(serious(await run(document.body))).toEqual([]);
  });
});
