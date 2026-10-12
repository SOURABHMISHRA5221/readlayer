import { afterEach, describe, expect, it } from "vitest";

import { ANNOTATOR_CSS, ANNOTATOR_VERSION, createAnnotator, renderPreread } from "../src/index";
import type { PrereadAnnotation } from "../src/types";
import pkg from "../package.json";

const PREREAD: PrereadAnnotation = {
  id: "pre",
  kind: "preread",
  score: 0.5,
  concept_id: "c_yield_curve",
  label: "the yield curve",
  steps: [{ concept_id: "c_bond", label: "Bond yields", definition: "What a bond pays.", content_id: null }],
};

function styleCount(): number {
  return document.querySelectorAll("style").length;
}

afterEach(() => {
  document.head.innerHTML = "";
  document.body.innerHTML = "";
});

describe("styles (0.8.0)", () => {
  it("injects one <style> by default, from both entry points", () => {
    document.body.innerHTML = `<article id="a"><p data-rl-paragraph="p0">Text.</p></article><div id="c"></div>`;
    createAnnotator(document.getElementById("a")!);
    renderPreread(document.getElementById("c")!, PREREAD, { href: () => "#" });
    expect(styleCount()).toBe(1);
    expect(document.querySelector("style")!.textContent).toBe(ANNOTATOR_CSS);
  });

  it('adds no <style> anywhere with styles: "external" (strict-CSP publisher pages)', () => {
    document.body.innerHTML = `<article id="a"><p data-rl-paragraph="p0">Text.</p></article><div id="c"></div>`;
    createAnnotator(document.getElementById("a")!, { styles: "external" });
    renderPreread(document.getElementById("c")!, PREREAD, { href: () => "#", styles: "external" });
    expect(styleCount()).toBe(0);
    expect(document.querySelector(".rl-preread")).not.toBeNull();
  });

  it("keeps the exported version and package.json in step", () => {
    expect(ANNOTATOR_VERSION).toBe(pkg.version);
  });
});
