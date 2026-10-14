import { afterEach, describe, expect, it } from "vitest";

import { AUTHOR_LABEL, CARD_LABEL, createAnnotator, HOST_UI, UI_ATTR, type CardAnnotation } from "../src/index";

// A transcript paragraph: the host's time button sits inside it, before the spoken text.
const HTML = `
  <article id="root">
    <p data-rl-paragraph="p0"><button ${UI_ATTR}="${HOST_UI}">0:02</button>The yield curve inverted.</p>
  </article>`;

const SPAN: CardAnnotation = {
  id: "yc",
  kind: "span",
  anchor: { exact: "yield curve", prefix: "The ", suffix: " inverted" },
  paragraph_id: "p0",
  score: 0.7,
  concept_id: "c_yc",
  label: "yield curve",
  definition: "Yields by maturity.",
  domain: "finance",
  prerequisites: [],
};

const root = () => document.getElementById("root") as HTMLElement;
const says = () => document.querySelector(".rl-card__says .rl-card__section-label")?.textContent;
const note = () => document.querySelector(".rl-card__note")?.textContent;

afterEach(() => {
  document.body.innerHTML = "";
});

describe("host options", () => {
  it("keeps the author wording by default", () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(root());
    expect(says()).toBe(AUTHOR_LABEL);
    expect(note()).toBe(CARD_LABEL);
    a.destroy();
  });

  it("uses the host's labels for a transcript", () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(root(), {
      labels: { author: "What the speaker is saying", card: "Explanation — not the speaker's words" },
    });
    expect(says()).toBe("What the speaker is saying");
    expect(note()).toBe("Explanation — not the speaker's words");
    a.destroy();
  });

  it("anchors past a host control and leaves it in place on destroy", async () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(root());
    const result = await a.update([SPAN]);
    expect(result.resolved).toEqual(["yc"]);
    a.destroy();
    const button = root().querySelector(`[${UI_ATTR}="${HOST_UI}"]`);
    expect(button?.textContent).toBe("0:02");
    expect(root().querySelector("[data-rl-id]")).toBeNull();
  });
});
