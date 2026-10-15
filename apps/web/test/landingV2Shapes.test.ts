import { describe, expect, it } from "vitest";

import { CLAUSES, FORMATS, LENGTHS, LEVELS, PROTECTED, SOURCE_TEXT, TAG, shape } from "../src/landing/v2/shapes";

// The /v2 concept's promise is "every line traces to its source": no shape may add a word.
const runs = (text: string) =>
  text
    .split("…")
    .map((r) => r.trim())
    .filter(Boolean);

/** Each run appears in `source` in order, without overlapping, matching case and punctuation. */
function inOrder(source: string, parts: readonly string[]): boolean {
  let from = 0;
  for (const part of parts) {
    const at = source.indexOf(part, from);
    if (at < 0) return false;
    from = at + part.length;
  }
  return true;
}

const all = LENGTHS.flatMap((l) => LEVELS.flatMap((v) => FORMATS.map((f) => [l.key, v.key, f.key] as const)));

describe("v2 shapes", () => {
  it("the clauses are the sentence's own text, in order, and cover it", () => {
    expect(inOrder(SOURCE_TEXT, CLAUSES.map((c) => c.text))).toBe(true);
    const words = (s: string) => s.replace(/[^\w()]+/g, " ").trim();
    expect(words(CLAUSES.map((c) => c.text).join(" "))).toBe(words(SOURCE_TEXT));
  });

  it("every shorter form is runs of its clause, in order", () => {
    for (const c of CLAUSES) {
      for (const form of [c.standard, c.simple]) if (form) expect(inOrder(c.text, runs(form)), form).toBe(true);
    }
  });

  it("the tag is the corpus paragraph id (p5) and the sentence", () => {
    expect(TAG).toBe("¶5 s1");
  });

  it.each(all)("%s / %s / %s: own words, in the sentence's order, nothing protected lost", (length, level, format) => {
    const lines = shape(length, level, format);
    expect(new Set(lines.map((l) => l.id)).size).toBe(lines.length);
    for (const line of lines) {
      const clause = CLAUSES.find((c) => c.id === line.id)!;
      expect(inOrder(clause.text, runs(line.text)), line.text).toBe(true);
      expect(line.tag).toBe(TAG);
    }
    expect(inOrder(SOURCE_TEXT, lines.flatMap((l) => runs(l.text)))).toBe(true);
    const shown = lines.map((l) => l.text).join(" ");
    for (const p of PROTECTED) expect(shown, p).toContain(p);
  });

  it("Full + Expert + Read is the whole sentence; shorter lengths keep fewer clauses", () => {
    expect(shape("full", "expert", "read").map((l) => l.text)).toEqual(CLAUSES.map((c) => c.text));
    expect(shape("2min", "standard", "read").length).toBeLessThan(shape("5min", "standard", "read").length);
    expect(shape("5min", "standard", "read").length).toBeLessThan(shape("full", "standard", "read").length);
  });

  it("listen and watch carry times from 0:00; read and scan don't", () => {
    const listen = shape("full", "standard", "listen");
    expect(listen[0]!.at).toBe("0:00");
    expect(listen.every((l) => /^\d+:\d\d$/.test(l.at ?? ""))).toBe(true);
    expect(shape("full", "standard", "scan").some((l) => l.at)).toBe(false);
  });
});
