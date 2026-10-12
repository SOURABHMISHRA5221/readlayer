import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { redact, redactUrl } from "../src/redact";

// The API's cases: both redactors must agree (apps/api/tests/test_redact.py reads the same file).
const CASES = JSON.parse(
  readFileSync(resolve(__dirname, "../../api/tests/fixtures/redaction.json"), "utf8"),
) as { redact: { in: string; out: string }[]; unchanged: string[] };

describe("redact (shared fixture with app/privacy/redact.py)", () => {
  it.each(CASES.redact)("redacts: $in", ({ in: input, out }) => {
    expect(redact(input)).toBe(out);
  });
  it.each(CASES.unchanged)("leaves news text alone: %s", (text) => {
    expect(redact(text)).toBe(text);
  });
});

describe("redactUrl", () => {
  it("drops the fragment and user info and redacts query values", () => {
    const url = redactUrl("https://me:pw@news.example/story?id=42&email=sam@x.com&ref=a#comments");
    expect(url).toBe("https://news.example/story?id=42&email=%5BREDACTED%3Aemail%5D&ref=a");
  });
  it("leaves a plain article URL as it was", () => {
    expect(redactUrl("https://news.example/2026/10/12/story")).toBe("https://news.example/2026/10/12/story");
  });
});
