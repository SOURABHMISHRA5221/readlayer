import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// @ts-expect-error: a plain ESM build script, no type declarations
import { evalNumbers, paths, renderEvalJson } from "../scripts/eval-numbers.mjs";

// Plan A5: the landing's verifier numbers come from the eval report, never typed by hand.
// CI doesn't run the web build (which regenerates evals.json), so this test is the guard.

describe("eval numbers", () => {
  it("the committed evals.json matches the eval report", () => {
    const report = readFileSync(paths.report, "utf8");
    expect(readFileSync(paths.out, "utf8")).toBe(renderEvalJson(report));
  });

  it("reads counts exactly and refuses a table it can't trust", () => {
    const table = (rows: string) =>
      `## Judge comparison\n| Judge | Adversarial rejected | Good accepted | Injection safe |\n|---|---|---|---|\n${rows}`;
    expect(evalNumbers(table("| `m` | 15/15 (100%) | 24/25 (96%) | 10/10 |"))).toEqual({
      judge: "m",
      adversarial: { passed: 15, total: 15 },
      good: { passed: 24, total: 25 },
      injection: { passed: 10, total: 10 },
    });
    expect(() => evalNumbers(table("| a | 1/1 | 1/1 | 1/1 |\n| b | 1/1 | 1/1 | 1/1 |"))).toThrow(/exactly one/);
    expect(() => evalNumbers(table("| a | all | 1/1 | 1/1 |"))).toThrow(/not "n\/m"/);
    expect(() => evalNumbers("## Other\n")).toThrow(/Judge comparison/);
  });
});
