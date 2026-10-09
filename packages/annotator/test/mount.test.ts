import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CARD_LABEL,
  createAnnotator,
  mount,
  type AnnotatorEvent,
  type CardAnnotation,
} from "../src/index";

const HTML = `
  <article id="root">
    <p data-rl-paragraph="p0">The <em>repo</em> rate rose while the yield curve inverted.</p>
    <p data-rl-paragraph="p1">Bond   markets watched the yield curve closely.</p>
  </article>
  <button id="after">after</button>`;

function annotation(
  id: string,
  exact: string,
  paragraph_id: string,
  extra: Partial<CardAnnotation> = {},
): CardAnnotation {
  return {
    id,
    kind: "span",
    anchor: { exact, prefix: "", suffix: "" },
    paragraph_id,
    score: 0.7,
    concept_id: `c_${id}`,
    label: exact,
    definition: `${exact} defined.`,
    domain: "finance",
    prerequisites: ["Bond", "Interest rate"],
    ...extra,
  };
}

async function setup(annotations: CardAnnotation[]) {
  document.body.innerHTML = HTML;
  const root = document.getElementById("root") as HTMLElement;
  const events: AnnotatorEvent[] = [];
  const before = root.textContent;
  const mounted = await mount(root, annotations, { onEvent: (e) => events.push(e) });
  return { root, events, before, mounted };
}

const card = () => document.querySelector<HTMLElement>(".rl-card")!;
const btn = (action: string) =>
  card().querySelector<HTMLButtonElement>(`button[data-action="${action}"]`)!;
const key = (el: Element, k: string, shift = false) =>
  el.dispatchEvent(new KeyboardEvent("keydown", { key: k, shiftKey: shift, bubbles: true }));

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("mount", () => {
  it("marks spans inside their paragraph without changing the text", async () => {
    const { root, before, mounted } = await setup([
      annotation("yc", "yield curve", "p1"),
      annotation("repo", "repo rate", "p0"), // crosses the <em>
      annotation("bm", "Bond markets", "p1"), // whitespace fallback
      annotation("missing", "quantitative easing", "p0"),
    ]);
    expect(root.textContent).toBe(before);
    expect(mounted.resolved).toEqual(["repo", "bm", "yc"]); // document order
    expect(mounted.unresolved).toEqual(["missing"]);
    const yc = root.querySelector('[data-rl-id="yc"]')!;
    expect(yc.closest("p")!.getAttribute("data-rl-paragraph")).toBe("p1");
    expect(root.querySelectorAll('[data-rl-id="repo"]').length).toBe(2);
  });

  it("skips an annotation that overlaps an earlier one", async () => {
    const { mounted } = await setup([
      annotation("a", "yield curve", "p0"),
      annotation("b", "curve inverted", "p0"),
    ]);
    expect(mounted.unresolved).toEqual(["b"]);
  });

  it("destroy restores the original DOM", async () => {
    const { root, mounted } = await setup([annotation("yc", "yield curve", "p0")]);
    const original = HTML.replace(/\s+/g, " ");
    mounted.destroy();
    expect(root.querySelector(".rl-mark")).toBeNull();
    expect(document.querySelector(".rl-card")).toBeNull();
    expect(root.querySelector("p")!.childNodes.length).toBe(3); // "The ", <em>, rest
    expect(document.body.innerHTML.replace(/\s+/g, " ")).toBe(original);
  });

  it("is keyboard operable with ARIA state and a focus trap", async () => {
    const { root, events } = await setup([annotation("yc", "yield curve", "p0", { debug: null })]);
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
    expect(card().querySelector(".rl-card__domain")!.textContent).toBe("finance");
    const chips = Array.from(card().querySelectorAll(".rl-chip")).map((c) => c.textContent);
    expect(chips).toEqual(["Bond", "Interest rate"]);
    expect(card().querySelector(".rl-card__debug")!.hasAttribute("hidden")).toBe(true);
    expect(events.map((e) => e.type)).toEqual(["explain_opened"]);

    const [knew, helpful] = [btn("knew_this"), btn("explain_helpful")];
    key(card(), "Tab");
    expect(document.activeElement).toBe(knew);
    helpful!.focus();
    key(helpful!, "Tab");
    expect(document.activeElement).toBe(knew); // wraps, never escapes
    key(knew!, "Tab", true);
    expect(document.activeElement).toBe(helpful);

    key(card(), "Escape");
    expect(card().hidden).toBe(true);
    expect(mark.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(mark);
  });

  it("buttons log events and mark the concept known", async () => {
    const { root, events } = await setup([annotation("yc", "yield curve", "p0")]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    key(mark, " ");
    const [knew, helpful] = [btn("knew_this"), btn("explain_helpful")];
    expect(helpful!.getAttribute("aria-label")).toBe("Helpful");
    knew!.click();
    helpful!.click();
    expect(events.map((e) => e.type)).toEqual(["explain_opened", "knew_this", "explain_helpful"]);
    expect(events[1]).toMatchObject({ annotation_id: "yc", concept_id: "c_yc" });
    expect(knew!.getAttribute("aria-pressed")).toBe("true");
    expect(mark.classList.contains("rl-mark--known")).toBe(true);
  });

  it("click toggles a pinned card and shows debug when present", async () => {
    const debug = { p_know: 0.27, salience: 0.9, span_score: 0.66, domain: "finance", base_difficulty: 1 };
    const { root } = await setup([annotation("yc", "yield curve", "p0", { debug })]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    mark.click();
    expect(card().hidden).toBe(false);
    expect(card().querySelector(".rl-card__debug")!.textContent).toContain("finance");
    mark.click();
    expect(card().hidden).toBe(true);
  });

  it("hover opens after a delay, reports hover, and closes after leaving", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = HTML;
    const root = document.getElementById("root") as HTMLElement;
    const hovers: (string | null)[] = [];
    const annotator = createAnnotator(root, { onHover: (id) => hovers.push(id), staggerMs: 0 });
    await annotator.update([annotation("yc", "yield curve", "p0")]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    mark.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
    expect(card().hidden).toBe(true);
    vi.advanceTimersByTime(130);
    expect(card().hidden).toBe(false);
    mark.dispatchEvent(new MouseEvent("pointerout", { bubbles: true, relatedTarget: document.body }));
    vi.advanceTimersByTime(300);
    expect(card().hidden).toBe(true);
    expect(hovers).toEqual(["yc", null]);
  });

  it("renders annotation text as text, never HTML", async () => {
    const { root } = await setup([
      annotation("yc", "yield curve", "p0", { definition: "<img src=x onerror=alert(1)>" }),
    ]);
    root.querySelector<HTMLElement>(".rl-mark")!.click();
    expect(card().querySelector("img")).toBeNull();
  });
});

describe("createAnnotator.update", () => {
  it("keeps shared marks, fades out removed ones, and staggers new ones in", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = HTML;
    const root = document.getElementById("root") as HTMLElement;
    const before = root.textContent;
    const annotator = createAnnotator(root, { leaveMs: 180, staggerMs: 20 });
    await annotator.update([annotation("yc", "yield curve", "p0"), annotation("repo", "repo rate", "p0")]);
    const kept = root.querySelector('[data-rl-id="yc"]');

    const pending = annotator.update([
      annotation("yc", "yield curve", "p0", { score: 0.9 }),
      annotation("bm", "Bond markets", "p1"),
      annotation("yc2", "yield curve", "p1"),
    ]);
    const leaving = root.querySelectorAll('[data-rl-id="repo"]');
    expect(leaving.length).toBe(2);
    leaving.forEach((m) => expect(m.classList.contains("rl-mark--leaving")).toBe(true));
    expect(leaving[0]!.hasAttribute("tabindex")).toBe(false);
    await vi.advanceTimersByTimeAsync(200);
    const result = await pending;

    expect(result.resolved).toEqual(["yc", "bm", "yc2"]);
    expect(root.querySelector('[data-rl-id="repo"]')).toBeNull();
    expect(root.querySelector('[data-rl-id="yc"]')).toBe(kept);
    expect(kept!.classList.contains("rl-mark--entering")).toBe(false);
    const bm = root.querySelector<HTMLElement>('[data-rl-id="bm"]')!;
    const yc2 = root.querySelector<HTMLElement>('[data-rl-id="yc2"]')!;
    expect(bm.classList.contains("rl-mark--entering")).toBe(true);
    expect([bm.style.animationDelay, yc2.style.animationDelay]).toEqual(["0ms", "20ms"]);
    expect(root.textContent).toBe(before);
  });

  it("a newer update supersedes one still fading out", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = HTML;
    const root = document.getElementById("root") as HTMLElement;
    const annotator = createAnnotator(root, { leaveMs: 180 });
    await annotator.update([annotation("yc", "yield curve", "p0")]);
    const first = annotator.update([annotation("bm", "Bond markets", "p1")]);
    const second = annotator.update([annotation("repo", "repo rate", "p0")]);
    await vi.advanceTimersByTimeAsync(400);
    await first;
    const result = await second;
    expect(result.resolved).toEqual(["repo"]);
    expect(root.querySelectorAll(".rl-mark[role=button]").length).toBe(1);
  });

  it("highlight links a mark and open() shows its card", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root") as HTMLElement;
    const actives: (string | null)[] = [];
    const annotator = createAnnotator(root, { onActive: (id) => actives.push(id), staggerMs: 0 });
    await annotator.update([annotation("yc", "yield curve", "p0")]);
    const mark = root.querySelector<HTMLElement>(".rl-mark")!;
    annotator.highlight("yc");
    expect(mark.classList.contains("rl-mark--linked")).toBe(true);
    annotator.highlight(null);
    expect(mark.classList.contains("rl-mark--linked")).toBe(false);
    annotator.open("yc", { focus: true });
    expect(card().hidden).toBe(false);
    expect(document.activeElement).toBe(card());
    annotator.close();
    expect(actives).toEqual(["yc", null]);
  });
});

describe("explanations", () => {
  const verified = (id: string, extra: Record<string, unknown> = {}) => ({
    id,
    kind: "verified" as const,
    background: "A curve of rates by maturity.",
    author_says: "The author says the curve inverted.",
    analogy_domain: null,
    ...extra,
  });

  async function withLoader(
    load: (a: CardAnnotation) => Promise<unknown>,
    extra: Record<string, unknown> = {},
  ) {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root") as HTMLElement;
    const events: AnnotatorEvent[] = [];
    const annotator = createAnnotator(root, {
      onEvent: (e) => events.push(e),
      loadExplanation: load as never,
      staggerMs: 0,
      ...extra,
    });
    const annotations = [annotation("yc", "yield curve", "p0"), annotation("rp", "repo", "p0")];
    await annotator.update(annotations, { reader: "newcomer" });
    return { annotator, events, annotations };
  }

  const flush = () => new Promise((r) => setTimeout(r, 0));
  const explainArea = () => card().querySelector<HTMLElement>(".rl-card__explain")!;
  const text = (cls: string) => card().querySelector(`.${cls} .rl-card__text`)!.textContent;

  it("keeps both labels while loading, then fills Background and What the author is saying", async () => {
    let resolve!: (e: unknown) => void;
    const { annotator } = await withLoader(() => new Promise((r) => (resolve = r)));
    annotator.open("yc");
    expect(explainArea().dataset.state).toBe("loading");
    expect(explainArea().getAttribute("aria-busy")).toBe("true");
    expect(card().querySelector(".rl-card__bg .rl-card__section-label")!.textContent).toBe("Background");
    expect(card().querySelector(".rl-card__says .rl-card__section-label")!.textContent).toBe(
      "What the author is saying",
    );
    expect(card().querySelector(".rl-card__status")!.textContent).toMatch(/checking it against/);
    // the definition fills the Background panel at once
    expect(text("rl-card__bg")).toBe("yield curve defined.");
    expect(btn("report_wrong").disabled).toBe(true);

    resolve(verified("k1"));
    await flush();
    expect(explainArea().dataset.state).toBe("ready");
    expect(text("rl-card__bg")).toBe("A curve of rates by maturity.");
    expect(text("rl-card__says")).toBe("The author says the curve inverted.");
    // replaced in place, under the same label: nothing above it moves
    expect(card().querySelector(".rl-card__bg .rl-card__section-label")!.textContent).toBe("Background");
    expect(card().querySelector<HTMLElement>(".rl-card__frame")!.hidden).toBe(true);
    expect(card().textContent).toContain(CARD_LABEL);
    expect(btn("report_wrong").disabled).toBe(false);
  });

  it("names the analogy frame on the Background panel", async () => {
    const { annotator } = await withLoader(async () =>
      verified("k1", { analogy_domain: "cricket" }),
    );
    annotator.open("yc");
    await flush();
    const frame = card().querySelector<HTMLElement>(".rl-card__bg .rl-card__frame")!;
    expect(frame.hidden).toBe(false);
    expect(frame.textContent).toBe("Analogy · cricket");
  });

  it("keeps only the definition when there is no verified explanation or the load fails", async () => {
    const { annotator } = await withLoader(async (a) =>
      a.id === "yc"
        ? { id: "k", kind: "definition", background: null, author_says: null }
        : Promise.reject(new Error("offline")),
    );
    for (const id of ["yc", "rp"]) {
      annotator.open(id);
      await flush();
      expect(card().querySelector(".rl-card__bg .rl-card__section-label")!.textContent).toBe("Definition");
      expect(text("rl-card__bg")).toBe(`${id === "yc" ? "yield curve" : "repo"} defined.`);
      expect(card().querySelector<HTMLElement>(".rl-card__says")!.hidden).toBe(true);
      expect(btn("report_wrong").hidden).toBe(true);
    }
  });

  it("ignores a response that arrives after the card moved to another span", async () => {
    const pending = new Map<string, (e: unknown) => void>();
    const { annotator } = await withLoader((a) => new Promise((r) => pending.set(a.id, r)));
    annotator.open("yc");
    annotator.open("rp");
    pending.get("yc")!(verified("old"));
    await flush();
    expect(explainArea().dataset.state).toBe("loading");
    pending.get("rp")!(verified("new", { author_says: "Repo rose." }));
    await flush();
    expect(text("rl-card__says")).toBe("Repo rose.");
  });

  it("This is wrong reports the explanation id and confirms", async () => {
    const { annotator, events } = await withLoader(async () => verified("k9"));
    annotator.open("yc");
    await flush();
    btn("report_wrong").click();
    const report = events.find((e) => e.type === "report_wrong");
    expect(report).toMatchObject({ annotation_id: "yc", explanation_id: "k9" });
    const status = card().querySelector(".rl-card__status")!;
    expect(status.textContent).toMatch(/removed/);
    expect(status.classList.contains("rl-card__status--visible")).toBe(true);
    expect(card().querySelector<HTMLElement>(".rl-card__says")!.hidden).toBe(true);
    expect(card().querySelector(".rl-card__bg .rl-card__section-label")!.textContent).toBe("Definition");
    expect(btn("report_wrong").getAttribute("aria-pressed")).toBe("true");
  });

  it("a persona switch reloads the open card and starts its actions fresh", async () => {
    const calls: string[] = [];
    let reader = "newcomer";
    const { annotator, annotations } = await withLoader(async () => {
      calls.push(reader);
      return verified(reader, { author_says: `For ${reader}.` });
    });
    annotator.open("yc");
    await flush();
    btn("knew_this").click();
    expect(btn("knew_this").getAttribute("aria-pressed")).toBe("true");

    reader = "trader";
    await annotator.update(annotations.map((a) => ({ ...a })), { reader: "trader" });
    await flush();
    expect(calls).toEqual(["newcomer", "trader"]);
    expect(text("rl-card__says")).toBe("For trader.");
    expect(btn("knew_this").getAttribute("aria-pressed")).toBe("false");
    expect(document.querySelector(".rl-mark--known")).toBeNull();
  });

  it("sets the card in the margin as a sidenote when the host offers a column", async () => {
    const { annotator } = await withLoader(async () => verified("k1"), {
      sidenote: () => ({ left: 900, width: 320 }),
    });
    annotator.open("yc");
    await flush();
    expect(card().dataset.mode).toBe("sidenote");
    expect(card().style.width).toBe("320px");
    expect(card().style.left).toBe("900px");
    expect(card().dataset.placement).toBe("right");
    // never taller than the window: the body scrolls, the actions stay pinned
    expect(card().style.maxHeight).toBe(`${window.innerHeight - 24}px`);
    expect(card().querySelector(".rl-card__body .rl-card__explain")).not.toBeNull();
    expect(card().querySelector(".rl-card__body .rl-card__footer")).toBeNull();
  });
});
