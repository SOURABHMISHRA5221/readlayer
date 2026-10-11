import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup, renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import demo from "../src/landing/demo.json";
import demoParagraph from "../src/landing/demoParagraph.json";
import { DEMO_PERSONAS } from "../src/landing/demoPersonas";
import { HeroStatic } from "../src/landing/Hero";

const INDEX = fileURLToPath(new URL("../index.html", import.meta.url));
const SLOT = /<!-- hero:start -->[\s\S]*<!-- hero:end -->/;

describe("static landing hero", () => {
  it("index.html carries exactly what HeroStatic renders (UPDATE_HERO=1 rewrites it)", () => {
    // renderToString (not static markup): its text separators let the landing hydrate this exact
    // DOM instead of replacing it (main.tsx, decision 47).
    const markup = `<!-- hero:start -->${renderToString(createElement(HeroStatic))}<!-- hero:end -->`;
    const html = readFileSync(INDEX, "utf8");
    expect(html).toMatch(SLOT);
    if (process.env.UPDATE_HERO === "1") writeFileSync(INDEX, html.replace(SLOT, () => markup));
    expect(readFileSync(INDEX, "utf8").match(SLOT)?.[0]).toBe(markup);
  });

  it("shows the demo paragraph and both calls to action before any script runs", () => {
    const html = renderToStaticMarkup(createElement(HeroStatic));
    expect(html).toContain(demo.paragraph.text);
    expect(html).toContain("Try it as a demo reader");
    expect(html).toContain("Sign in with Google");
    expect(html).toContain('class="lp lp--static"');
  });
});

describe("demo data", () => {
  it("the hero's paragraph file is demo.json without the notes (build_landing_demo.py writes both)", () => {
    const { personas: _personas, ...rest } = demo;
    expect(demoParagraph).toEqual(rest);
  });
});

describe("demo persona labels", () => {
  it("match demo.json, in the order the toggle shows them", () => {
    expect(DEMO_PERSONAS.map((p) => p.key)).toEqual(Object.keys(demo.personas));
    for (const p of DEMO_PERSONAS) {
      expect(demo.personas[p.key as keyof typeof demo.personas].label).toBe(p.label);
    }
  });
});
