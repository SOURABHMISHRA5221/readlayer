import { describe, expect, it } from "vitest";

import { BAND_GLYPH, evidenceText, previewLines, thetaPercent, thetaText, thetaWord } from "../src/lib/profileFormat";

describe("profile wording", () => {
  it("turns evidence into plain language with a date", () => {
    expect(evidenceText("explain_opened", "2026-10-03T10:00:00Z")).toBe("You opened an explanation · 3 Oct");
    expect(evidenceText("seed", "2026-10-01T10:00:00Z")).toMatch(/^Part of this sample reader's starting point/);
    expect(evidenceText("something_new", "2026-10-01T10:00:00Z")).toMatch(/^Reading activity/);
  });

  it("maps ability onto a fixed −2..2 scale and words", () => {
    expect(thetaPercent(-2)).toBe(0);
    expect(thetaPercent(0)).toBe(50);
    expect(thetaPercent(5)).toBe(100);
    expect([thetaWord(1.2), thetaWord(0.3), thetaWord(-0.5), thetaWord(-1.5)]).toEqual([
      "advanced", "comfortable", "building", "new",
    ]); // prettier-ignore
    expect([thetaText(-0.03), thetaText(0.64), thetaText(-1.5)]).toEqual(["0.0", "+0.6", "−1.5"]);
    expect(thetaWord(-0.03)).toBe("comfortable"); // judged as shown: 0.0
  });

  it("gives every band a shape, not only a colour", () => {
    expect(new Set(Object.values(BAND_GLYPH)).size).toBe(4);
  });

  it("lists a preview's changes one per line", () => {
    const lines = previewLines({
      domains: [{ domain: "finance", before: 0, after: 0.75 }],
      known: [{ concept_id: "c_options", label: "Options" }],
      unknown: [],
      settings: [
        { setting: "explanation_style", before: "normal", after: "short" },
        { setting: "thinks_in", before: [], after: ["software"] },
      ],
      unresolved: [],
    });
    expect(lines).toEqual([
      "finance: ability 0.0 → 0.8",
      "1 concept marked as known",
      "Explanation length: normal → short",
      "Analogies from: none → software",
    ]);
  });
});
