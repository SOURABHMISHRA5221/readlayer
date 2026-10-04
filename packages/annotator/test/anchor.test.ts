import { describe, expect, it } from "vitest";

import { normalizeWhitespace, resolveInText } from "../src/anchor";

describe("resolveInText", () => {
  const text = "The rate rose. Then the repo rate fell, and the repo rate was cut again.";

  it("picks the occurrence whose prefix and suffix match", () => {
    const r = resolveInText(text, { exact: "repo rate", prefix: "and the ", suffix: " was" });
    expect(r).toEqual({ start: text.lastIndexOf("repo rate"), end: text.lastIndexOf("repo rate") + 9 });
  });

  it("uses the offset hint to break ties", () => {
    const anchor = { exact: "repo rate", prefix: "", suffix: "" };
    expect(resolveInText(text, anchor, 60)?.start).toBe(text.lastIndexOf("repo rate"));
    expect(resolveInText(text, anchor, 0)?.start).toBe(text.indexOf("repo rate"));
  });

  it("falls back to whitespace-normalized matching", () => {
    const raw = "the inverted yield\n   curve has historically";
    const r = resolveInText(raw, { exact: "yield curve", prefix: "inverted ", suffix: " has" });
    expect(r).not.toBeNull();
    expect(raw.slice(r!.start, r!.end)).toBe("yield\n   curve");
  });

  it("returns null when the text is absent", () => {
    expect(resolveInText(text, { exact: "yield curve", prefix: "", suffix: "" })).toBeNull();
    expect(resolveInText(text, { exact: "", prefix: "", suffix: "" })).toBeNull();
  });

  it("normalizes NBSP and runs", () => {
    expect(normalizeWhitespace("a  b \n c").text).toBe("a b c");
  });
});
