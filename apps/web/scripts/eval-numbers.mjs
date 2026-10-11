// The landing's verifier numbers (plan A5), read from the eval report's "Judge comparison" table
// and written to src/landing/evals.json. Runs before every web build and in a vitest, so a stale
// copy fails CI. Never rounds: the page shows "15 of 15" exactly as the report counts it.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const REPORT = fileURLToPath(new URL("../../api/evals/report.md", import.meta.url));
const OUT = fileURLToPath(new URL("../src/landing/evals.json", import.meta.url));

const COLUMNS = {
  adversarial: "Adversarial rejected",
  good: "Good accepted",
  injection: "Injection safe",
};

function cells(line) {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
}

/** "15/15 (100%)" → { passed: 15, total: 15 }. */
function count(cell, column) {
  const m = /^(\d+)\/(\d+)\b/.exec(cell ?? "");
  if (!m) throw new Error(`eval-numbers: "${column}" is not "n/m": ${cell}`);
  return { passed: Number(m[1]), total: Number(m[2]) };
}

/** The numbers from the report's markdown; throws unless the table has exactly one judge row. */
export function evalNumbers(markdown) {
  const section = markdown.split(/^## /m).find((s) => s.startsWith("Judge comparison"));
  if (!section) throw new Error('eval-numbers: no "## Judge comparison" section in the report');
  const table = section.split("\n").filter((l) => l.trim().startsWith("|"));
  const [header, , ...rows] = table;
  if (!header) throw new Error("eval-numbers: the judge table has no header");
  if (rows.length !== 1) throw new Error(`eval-numbers: expected exactly one judge row, found ${rows.length}`);
  const names = cells(header);
  const row = cells(rows[0]);
  const at = (column) => {
    const i = names.indexOf(column);
    if (i < 0) throw new Error(`eval-numbers: no "${column}" column`);
    return row[i];
  };
  return {
    judge: at("Judge").replaceAll("`", ""),
    adversarial: count(at(COLUMNS.adversarial), COLUMNS.adversarial),
    good: count(at(COLUMNS.good), COLUMNS.good),
    injection: count(at(COLUMNS.injection), COLUMNS.injection),
  };
}

export function renderEvalJson(markdown) {
  return `${JSON.stringify(evalNumbers(markdown), null, 2)}\n`;
}

export const paths = { report: REPORT, out: OUT };

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  writeFileSync(OUT, renderEvalJson(readFileSync(REPORT, "utf8")));
}
