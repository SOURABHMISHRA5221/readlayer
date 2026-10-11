import { afterEach, describe, expect, it } from "vitest";

import { createAnnotator, renderPreread, type CardAnnotation, type Explanation } from "../src/index";

const HTML = `<article id="root"><p data-rl-paragraph="p0">The repo rate rose while the yield curve inverted.</p></article>`;

function span(id: string, exact: string, extra: Partial<CardAnnotation> = {}): CardAnnotation {
  return {
    id, kind: "span", anchor: { exact, prefix: "", suffix: "" }, paragraph_id: "p0", score: 0.7,
    concept_id: `c_${id}`, label: exact, definition: `${exact} defined.`, domain: "finance",
    prerequisites: ["Bond"], ...extra,
  };  // prettier-ignore
}

const verified = (band: string, extra: Partial<Explanation> = {}): Explanation => ({
  id: `x-${band}`, kind: "verified", background: `Background at ${band}.`, author_says: "The author says so.",
  band, can_simpler: band !== "unaware", can_deeper: band !== "can explain", ...extra,
});  // prettier-ignore

const card = () => document.querySelector<HTMLElement>(".rl-card")!;
const tick = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  document.body.innerHTML = "";
});

describe("Gloss highlight levels and card", () => {
  it("marks new and refresher spans differently; a missing level means new", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const a = createAnnotator(root, {});
    await a.update([span("repo", "repo rate", { level: "refresher" }), span("yc", "yield curve")]);
    expect(root.querySelector('[data-rl-id="repo"]')!.classList.contains("rl-mark--refresher")).toBe(true);
    expect(root.querySelector('[data-rl-id="yc"]')!.classList.contains("rl-mark--new")).toBe(true);
    expect(root.textContent).toBe("The repo rate rose while the yield curve inverted."); // text untouched
    a.destroy();
  });

  it("shows the pitch from the explanation's band and Builds on before the Background", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const a = createAnnotator(root, { loadExplanation: async () => verified("heard of") });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    const pitch = card().querySelector<HTMLElement>(".rl-card__pitch")!;
    expect(pitch.hidden).toBe(false);
    expect(pitch.textContent).toBe("You've heard of this, so it skips the basics");
    expect(card().querySelectorAll(".rl-card__meter .on")).toHaveLength(2);
    expect(card().querySelector(".rl-card__prereq-label")!.textContent).toBe("Builds on");
    const order = Array.from(card().querySelector(".rl-card__body")!.children).map((c) => c.className);
    expect(order.indexOf("rl-card__prereqs")).toBeLessThan(order.indexOf("rl-card__explain"));
    expect(card().querySelector<HTMLElement>(".rl-card__depth")!.hidden).toBe(true); // no loadShifted
    a.destroy();
  });

  it("Say it simpler loads the band below and toggles back to the reader's level", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const shifts: number[] = [];
    const a = createAnnotator(root, {
      loadExplanation: async () => verified("understands"),
      loadShifted: async (_x, shift) => {
        shifts.push(shift);
        return verified(shift < 0 ? "heard of" : "can explain");
      },
    });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    const [simpler, deeper] = Array.from(card().querySelectorAll<HTMLButtonElement>(".rl-btn--depth"));
    expect(card().querySelector<HTMLElement>(".rl-card__depth")!.hidden).toBe(false);
    expect([simpler!.textContent, deeper!.textContent]).toEqual(["Say it simpler", "Go deeper"]);
    simpler!.click();
    await tick();
    expect(shifts).toEqual([-1]);
    expect(card().textContent).toContain("Background at heard of.");
    expect(card().querySelector(".rl-card__pitch")!.textContent).toBe("Simpler than your level");
    expect(simpler!.textContent).toBe("Back to my level");
    expect(simpler!.getAttribute("aria-pressed")).toBe("true");
    simpler!.click();
    await tick();
    expect(shifts).toEqual([-1]); // back to the reader's own level uses the normal loader
    expect(card().textContent).toContain("Background at understands.");
    a.destroy();
  });
});

describe("pre-read card in the extension", () => {
  it("skips the known step the path starts from", () => {
    document.body.innerHTML = `<div id="slot"></div>`;
    renderPreread(
      document.getElementById("slot")!,
      {
        id: "preread", kind: "preread", score: 0.6, concept_id: "c_yc", label: "yield curve",
        steps: [
          { concept_id: "c_rate", label: "Repo rate", definition: "A rate.", known: true },
          { concept_id: "c_yc", label: "Yield curve", definition: "A curve." },
        ],
      },  // prettier-ignore
      { href: () => "#" },
    );
    const steps = Array.from(document.querySelectorAll(".rl-preread li")).map((li) => li.textContent);
    expect(steps).toHaveLength(1);
    expect(steps[0]).toContain("Yield curve");
  });
});

describe("a rejected shifted Background", () => {
  it("keeps Back to my level", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const a = createAnnotator(root, {
      loadExplanation: async () => verified("understands"),
      loadShifted: async () => ({ id: "", kind: "verified", background: null, author_says: "The author says so.", band: "heard of" }),
    });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    const simpler = card().querySelector<HTMLButtonElement>(".rl-btn--depth")!;
    simpler.click();
    await tick();
    expect(card().querySelector<HTMLElement>(".rl-card__depth")!.hidden).toBe(false);
    expect(simpler.textContent).toBe("Back to my level");
    a.destroy();
  });
});

describe("demo card actions (landing page)", () => {
  it("replaces Knew this / Helpful / This is wrong with one call to action and records nothing", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const events: string[] = [];
    let ctas = 0;
    const a = createAnnotator(root, {
      actions: "demo",
      demoAction: { label: "Try it on any article", onClick: () => ctas++ },
      loadExplanation: async () => verified("heard of"),
      onEvent: (e) => events.push(e.type),
    });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    const buttons = Array.from(card().querySelectorAll<HTMLButtonElement>(".rl-card__actions button"));
    expect(buttons.map((b) => b.textContent)).toEqual(["Try it on any article"]);
    buttons[0]!.click();
    expect(ctas).toBe(1);
    expect(events.filter((t) => t !== "explain_opened")).toEqual([]);
    a.destroy();
  });

  it("keeps the full actions by default", async () => {
    document.body.innerHTML = HTML;
    const root = document.getElementById("root")!;
    const a = createAnnotator(root, { loadExplanation: async () => verified("heard of") });
    await a.update([span("yc", "yield curve")]);
    a.open("yc");
    await tick();
    expect(card().querySelectorAll(".rl-card__actions button").length).toBe(3);
    a.destroy();
  });
});
