import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { extractArticle } from "../src/extract";

const load = (name: string) =>
  new DOMParser().parseFromString(readFileSync(resolve(__dirname, "fixtures", name), "utf8"), "text/html");

// Three common publisher layouts, synthetic text (no publisher's article is kept in the repo).
const LAYOUTS = [
  ["layout-article-body.html", 4, "The central bank kept its policy rate", "Bond markets brace"],
  ["layout-text-blocks.html", 4, "When long-term borrowing costs fall", "Why the yield curve"],
  ["layout-div-paragraphs.html", 4, "The government on Monday extended", "Government extends"],
] as const;

describe("extractArticle", () => {
  it.each(LAYOUTS)("%s: article paragraphs only", (file, count, first, title) => {
    const doc = load(file);
    const before = doc.documentElement.outerHTML;
    const got = extractArticle(doc)!;
    expect(got.title.startsWith(title)).toBe(true);
    expect(got.paragraphs.length).toBeGreaterThanOrEqual(count);
    expect(got.paragraphs.some((p) => p.startsWith(first))).toBe(true);
    const all = got.paragraphs.join("\n");
    for (const junk of ["Comments", "fiscal deficit and borrowing", "desk@dailyledger", "Sign up", "Trending", "Advertisement"]) {
      expect(all).not.toContain(junk);
    }
    expect(doc.documentElement.outerHTML).toBe(before); // the live page is never touched
  });
});
