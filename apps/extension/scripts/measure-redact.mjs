// M8 acceptance 5, extension side: what redact.ts changes in the stored corpus. Offline, over the
// read-only export (apps/api: uv run python -m scripts.export_corpus_text). Prints placeholder
// types per changed paragraph; --show adds the matched text for a local look only.
//   node --experimental-strip-types scripts/measure-redact.mjs [--show]
import { readFileSync } from "node:fs";

import { redact } from "../src/redact.ts";

const docs = JSON.parse(readFileSync(new URL("../../../data/corpus_paragraphs.json", import.meta.url), "utf8"));
const show = process.argv.includes("--show");
let total = 0;
const changed = [];
for (const d of docs) {
  for (const p of d.paragraphs) {
    total += 1;
    const out = redact(p.text);
    if (out !== p.text) changed.push([d, p, out]);
  }
}
console.log(`${docs.length} docs; redact.ts changed ${changed.length} of ${total} paragraphs`);
for (const [d, p, out] of changed) {
  console.log(`- ${d.content_id.slice(0, 8)} ${d.source} ${p.id}: ${JSON.stringify(out.match(/\[REDACTED:\w+\]/g))}`);
  if (show) {
    const words = p.text.split(/\s+/).filter((w) => !out.includes(w));
    console.log(`    matched: ${JSON.stringify(words)}`);
  }
}
