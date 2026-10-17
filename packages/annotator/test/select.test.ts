// Decision 70 Fix 3: select a word or phrase, press "Explain", the host opens its card. The host
// gets paragraph offsets, never the selected text.
import { afterEach, describe, expect, it } from "vitest";

import { createAnnotator, type CardAnnotation, type SelectionAsk } from "../src/index";

const P0 = "The repo rate rose while the yield curve inverted.";
const HTML = `<article id="root">
  <p data-rl-paragraph="p0">${P0}</p>
  <p data-rl-paragraph="p1">Bond markets watched closely.</p>
</article>`;

const span = (id: string, exact: string): CardAnnotation => ({
  id, kind: "span", anchor: { exact, prefix: "", suffix: "" }, paragraph_id: "p0", score: 0.7,
  concept_id: `c_${id}`, label: exact, definition: `${exact} defined.`, domain: "finance", prerequisites: [],
});  // prettier-ignore

const button = () => document.querySelector<HTMLButtonElement>(".rl-select");
const para = (id: string) => document.querySelector<HTMLElement>(`[data-rl-paragraph="${id}"]`)!;

/** Select `part` of a paragraph's article text (skipping our controls), then release the pointer. */
function select(pid: string, part: string, endPid = pid, endPart = part) {
  const range = document.createRange();
  const [sNode, sOff] = point(para(pid), part, false);
  const [eNode, eOff] = point(para(endPid), endPart, true);
  range.setStart(sNode, sOff);
  range.setEnd(eNode, eOff);
  const sel = document.getSelection()!;
  sel.removeAllRanges();
  sel.addRange(range);
  document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
}

function point(el: HTMLElement, part: string, end: boolean): [Text, number] {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
    const at = n.data.indexOf(part);
    if (at >= 0) return [n, end ? at + part.length : at];
  }
  throw new Error(`no text node holds "${part}"`);
}

afterEach(() => {
  document.getSelection()?.removeAllRanges();
  document.body.innerHTML = "";
});

describe("Explain a selection", () => {
  it("a selection in one paragraph shows the button; a click sends offsets and hides it", async () => {
    document.body.innerHTML = HTML;
    const asked: SelectionAsk[] = [];
    const a = createAnnotator(document.getElementById("root")!, { onSelectionExplain: (s) => asked.push(s) });
    await a.update([]);
    select("p0", "yield curve");
    const b = button()!;
    expect(b).not.toBeNull();
    expect(b.textContent).toBe("Explain");
    expect(b.getAttribute("aria-label")).toBe("Explain this");
    b.click();
    const start = P0.indexOf("yield curve");
    expect(asked).toEqual([{ paragraph_id: "p0", start, end: start + "yield curve".length }]);
    expect(JSON.stringify(asked)).not.toContain("yield");
    expect(button()).toBeNull();
    a.destroy();
  });

  it("offsets skip our controls: after a ¶ marker and inside a marked word", async () => {
    document.body.innerHTML = HTML;
    const asked: SelectionAsk[] = [];
    const a = createAnnotator(document.getElementById("root")!, { onSelectionExplain: (s) => asked.push(s) });
    await a.update([
      span("repo", "repo rate"),
      { id: "para:p0", kind: "paragraph", paragraph_id: "p0", score: 0.5 },
    ]);
    expect(para("p0").querySelector(".rl-pmark")).not.toBeNull();
    select("p0", "rate", "p0", " rose");
    button()!.click();
    const start = P0.indexOf("rate rose");
    expect(asked).toEqual([{ paragraph_id: "p0", start, end: start + "rate rose".length }]);
    a.destroy();
  });

  it("trims spaces at either end of the selection", async () => {
    document.body.innerHTML = HTML;
    const asked: SelectionAsk[] = [];
    const a = createAnnotator(document.getElementById("root")!, { onSelectionExplain: (s) => asked.push(s) });
    await a.update([]);
    select("p0", " yield curve ");
    button()!.click();
    const start = P0.indexOf("yield curve");
    expect(asked[0]).toEqual({ paragraph_id: "p0", start, end: start + "yield curve".length });
    a.destroy();
  });

  it("no button across two paragraphs, for one character, or inside the card", async () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(document.getElementById("root")!, { onSelectionExplain: () => undefined });
    await a.update([span("repo", "repo rate")]);
    select("p0", "inverted.", "p1", "Bond");
    expect(button()).toBeNull();
    select("p0", "y");
    expect(button()).toBeNull();
    a.open("repo");
    const card = document.querySelector<HTMLElement>(".rl-card")!;
    const range = document.createRange();
    range.selectNodeContents(card);
    document.getSelection()!.removeAllRanges();
    document.getSelection()!.addRange(range);
    document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    expect(button()).toBeNull();
    a.destroy();
  });

  it("Escape and a collapsed selection hide it", async () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(document.getElementById("root")!, { onSelectionExplain: () => undefined });
    await a.update([]);
    select("p0", "yield curve");
    expect(button()).not.toBeNull();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(button()).toBeNull();
    select("p0", "yield curve");
    document.getSelection()!.removeAllRanges();
    document.dispatchEvent(new KeyboardEvent("keyup", { key: "Shift", bubbles: true }));
    expect(button()).toBeNull();
    a.destroy();
  });

  it("follows the selection on scroll instead of vanishing", async () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(document.getElementById("root")!, { onSelectionExplain: () => undefined });
    await a.update([]);
    select("p0", "yield curve");
    window.dispatchEvent(new Event("scroll"));
    await new Promise((r) => setTimeout(r, 50));
    expect(button()).not.toBeNull();
    a.destroy();
  });

  it("is off unless the host asks for it", async () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(document.getElementById("root")!);
    await a.update([]);
    select("p0", "yield curve");
    expect(button()).toBeNull();
    a.destroy();
  });

  it("touch: a selection changed by its handles shows the button after a short pause", async () => {
    document.body.innerHTML = HTML;
    const a = createAnnotator(document.getElementById("root")!, { onSelectionExplain: () => undefined });
    await a.update([]);
    const range = document.createRange();
    const [n, at] = point(para("p0"), "yield curve", false);
    range.setStart(n, at);
    range.setEnd(n, at + "yield curve".length);
    document.getSelection()!.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    expect(button()).toBeNull(); // debounced
    await new Promise((r) => setTimeout(r, 400));
    expect(button()).not.toBeNull();
    a.destroy();
  });
});
