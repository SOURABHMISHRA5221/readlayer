// M8 acceptance 4: the built manifest asks for activeTab, scripting and storage only, with no
// host permissions and no content scripts. Fails the build otherwise.
import { readFileSync } from "node:fs";

const m = JSON.parse(readFileSync(new URL("../dist/manifest.json", import.meta.url), "utf8"));
const problems = [];
const perms = [...(m.permissions ?? [])].sort();
if (JSON.stringify(perms) !== JSON.stringify(["activeTab", "scripting", "storage"])) problems.push(`permissions ${perms}`);
for (const key of ["host_permissions", "optional_host_permissions", "optional_permissions", "content_scripts"]) {
  if (key in m) problems.push(`${key} present`);
}
if (JSON.stringify(m).includes("<all_urls>")) problems.push("<all_urls> present");
for (const match of m.externally_connectable?.matches ?? []) {
  if (!/^https?:\/\/[^*/]+\/\*$/.test(match)) problems.push(`externally_connectable ${match}`);
}
if (problems.length) {
  console.error(`manifest check failed: ${problems.join("; ")}`);
  process.exit(1);
}
console.info("manifest check: activeTab, scripting, storage only; no host permissions, no content scripts");
