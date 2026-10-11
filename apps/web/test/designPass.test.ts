import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Margo } from "../src/components/Margo";
import { parseTab, tabParam, TABS } from "../src/lib/libraryTabs";

describe("Margo", () => {
  it("is always decorative and only the idle mood blinks", () => {
    for (const mood of ["idle", "think", "happy", "oops", "mark"] as const) {
      const html = renderToStaticMarkup(createElement(Margo, { mood, blink: true }));
      expect(html).toContain('aria-hidden="true"');
      expect(html).toContain('focusable="false"');
      expect(html.includes("margo--blink")).toBe(mood === "idle");
    }
  });
});

describe("library tabs and the URL", () => {
  it("reads the tab from the URL, For you by default and on /for-you", () => {
    expect(parseTab(new URL("https://x.test/"))).toBe("foryou");
    expect(parseTab(new URL("https://x.test/?tab=topics"))).toBe("topics");
    expect(parseTab(new URL("https://x.test/?tab=saved&persona=trader"))).toBe("saved");
    expect(parseTab(new URL("https://x.test/?tab=bogus"))).toBe("foryou");
    expect(parseTab(new URL("https://x.test/for-you?tab=topics"))).toBe("foryou");
  });

  it("round-trips every tab", () => {
    for (const t of TABS) {
      const param = tabParam(t.id);
      const url = new URL(`https://x.test/${param ? `?tab=${param}` : ""}`);
      expect(parseTab(url)).toBe(t.id);
    }
  });
});

import { cleanSnippet } from "../src/components/library/Row";

describe("feed snippets", () => {
  it("drop markdown marks and links", () => {
    expect(cleanSnippet("Go to https://surfshark.com/economics or use code X. ## Big promises **now**")).toBe(
      "Go to or use code X. Big promises now",
    );
  });
});
