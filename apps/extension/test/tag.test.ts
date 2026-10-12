import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { extractArticle } from "../src/extract";
import { redact } from "../src/redact";
import { PARAGRAPH_ATTR, tagParagraphs } from "../src/tag";

const load = (name: string) =>
  new DOMParser().parseFromString(readFileSync(resolve(__dirname, "fixtures", name), "utf8"), "text/html");

const asServer = (texts: string[]) => texts.map((text, i) => ({ id: `p${i}`, text: redact(text) }));

describe("tagParagraphs", () => {
  it.each(["layout-article-body.html", "layout-text-blocks.html", "layout-div-paragraphs.html"])(
    "%s: tags the deepest element per paragraph and changes no text",
    (file) => {
      const doc = load(file);
      const text = doc.body.textContent;
      const paragraphs = asServer(extractArticle(doc)!.paragraphs);
      const tagged = tagParagraphs(doc, paragraphs)!;
      expect(tagged.unmatched).toEqual([]);
      expect(doc.body.textContent).toBe(text);
      for (const [id, el] of tagged.elements) {
        expect(el.getAttribute(PARAGRAPH_ATTR)).toBe(id);
        expect(el.querySelector(`[${PARAGRAPH_ATTR}]`)).toBeNull();
        expect(tagged.root.contains(el)).toBe(true);
      }
    },
  );

  it("matches a paragraph whose email the server redacted", () => {
    const doc = new DOMParser().parseFromString(
      "<main><p>Readers can send tips to the desk at tips@news.example, the editor said on Monday.</p></main>",
      "text/html",
    );
    const server = [{ id: "p0", text: "Readers can send tips to the desk at [REDACTED:email], the editor said on Monday." }];
    expect(tagParagraphs(doc, server)!.elements.get("p0")!.tagName).toBe("P");
  });

  it("falls back to a prefix match for the fetch path's own extraction", () => {
    const doc = new DOMParser().parseFromString(
      "<main><p>The government on Monday extended the export incentive scheme for another year, giving exporters more time. <a>Read more</a></p></main>",
      "text/html",
    );
    const server = [{ id: "p0", text: "The government on Monday extended the export incentive scheme for another year, giving exporters more time." }];
    expect(tagParagraphs(doc, server)!.unmatched).toEqual([]);
  });

  it("returns null when nothing matches", () => {
    const doc = new DOMParser().parseFromString("<p>Something else entirely on this page today.</p>", "text/html");
    expect(tagParagraphs(doc, [{ id: "p0", text: "A paragraph that is not on the page at all, anywhere." }])).toBeNull();
  });
});
