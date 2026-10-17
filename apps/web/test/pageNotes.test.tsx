// @vitest-environment jsdom
// Decision 70: the ¶ paragraph notes are notes too: counted and listed with the underlined words.
import type { CardAnnotation, ParagraphMarker } from "@readlayer/annotator";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { ConceptRail } from "../src/components/ConceptRail";
import { pageNotes } from "../src/lib/pageNotes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const paragraphs = [
  { id: "p0", text: "First paragraph." },
  { id: "p1", text: "The repo rate rose." },
  { id: "p2", text: "Third paragraph." },
];

const span = (id: string, paragraph_id: string, exact: string): CardAnnotation => ({
  id, kind: "span", anchor: { exact, prefix: "", suffix: "" }, paragraph_id, score: 0.7,
  concept_id: `c_${id}`, label: exact, definition: `${exact} defined.`, domain: "finance", prerequisites: [],
});  // prettier-ignore

const marker = (paragraph_id: string): ParagraphMarker => ({
  id: `para:${paragraph_id}`, kind: "paragraph", paragraph_id, score: 0.5, domain: "finance",
});  // prettier-ignore

describe("pageNotes", () => {
  it("two ¶ notes and one word are three notes, in document order, ¶ before its paragraph's words", () => {
    const notes = pageNotes([span("repo", "p1", "repo rate")], ["para:p1", "para:p2"], [marker("p2"), marker("p1")], paragraphs);
    expect(notes.map((n) => n.id)).toEqual(["para:p1", "repo", "para:p2"]);
    expect(notes.map((n) => n.label)).toEqual(["Paragraph 2", "repo rate", "Paragraph 3"]);
    expect(notes[0]!.kind).toBe("paragraph");
  });

  it("only ¶ notes still count, and unplaced markers don't", () => {
    const notes = pageNotes([], ["para:p0", "para:p2"], [marker("p0"), marker("p2"), marker("p1")], paragraphs);
    expect(notes.map((n) => n.id)).toEqual(["para:p0", "para:p2"]);
  });
});

let host: HTMLDivElement;
let root: Root;

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
});

describe("the margin counts ¶ notes", () => {
  it('says "3 notes for you" and a ¶ item opens its paragraph card', async () => {
    const opened: string[] = [];
    const notes = pageNotes([span("repo", "p1", "repo rate")], ["para:p0", "para:p2"], [marker("p0"), marker("p2")], paragraphs);
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () =>
      root.render(
        <ConceptRail items={notes} hovered={null} active={null} onHighlight={() => undefined} onOpen={(id) => opened.push(id)} />,
      ),
    );
    expect(host.querySelector(".rail__head")!.textContent).toContain("3 notes for you");
    const items = [...host.querySelectorAll<HTMLButtonElement>(".rail__item")];
    expect(items.map((b) => b.textContent)).toEqual([
      "Paragraph 1, what it's saying",
      "repo rate, new to you",
      "Paragraph 3, what it's saying",
    ]);
    expect(items[0]!.dataset.kind).toBe("paragraph");
    await act(async () => items[2]!.click());
    expect(opened).toEqual(["para:p2"]);
  });
});
