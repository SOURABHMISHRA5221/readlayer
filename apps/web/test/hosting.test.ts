import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Decision 69 E: HTML revalidates on every load, hashed assets are cached for good, and the SPA
// rewrite never swallows a file. Hosting regexes are RE2 (no lookaround), which the emulator
// doesn't enforce, so this test is the guard.

interface Header { key: string; value: string }
interface HeaderRule { source?: string; regex?: string; headers: Header[] }
interface Rewrite { source?: string; regex?: string; destination: string }
interface Target { target: string; headers: HeaderRule[]; rewrites: Rewrite[] }

const config = JSON.parse(readFileSync(new URL("../../../firebase.json", import.meta.url), "utf8"));
const targets: Target[] = config.hosting;

function matches(rule: { source?: string; regex?: string }, path: string): boolean {
  if (rule.regex) return new RegExp(rule.regex).test(path);
  if (rule.source === "**") return true;
  if (rule.source?.endsWith("/**")) return path.startsWith(rule.source.slice(0, -2));
  return rule.source === path;
}

function cacheControl(t: Target, path: string): string[] {
  return t.headers
    .filter((r) => matches(r, path))
    .flatMap((r) => r.headers.filter((h) => h.key === "Cache-Control").map((h) => h.value));
}

describe("hosting (decision 69 E)", () => {
  it("both sites are configured the same way", () => {
    expect(targets.map((t) => t.target).sort()).toEqual(["app", "gloss"]);
    expect(targets[0].headers).toEqual(targets[1].headers);
    expect(targets[0].rewrites).toEqual(targets[1].rewrites);
  });

  it("no regex uses lookaround (RE2 rejects it)", () => {
    const regexes = targets.flatMap((t) => [...t.headers, ...t.rewrites]).flatMap((r) => (r.regex ? [r.regex] : []));
    expect(regexes.length).toBeGreaterThan(0);
    for (const r of regexes) expect(r).not.toMatch(/\(\?[=!<]/);
  });

  it("pages and the unhashed script revalidate; hashed assets are immutable; fonts keep theirs", () => {
    for (const t of targets) {
      for (const p of ["/", "/welcome", "/read/abc_-1", "/index.html", "/theme-init.js"]) {
        expect(cacheControl(t, p), p).toEqual(["no-cache"]);
      }
      expect(cacheControl(t, "/assets/index-abc.js")).toEqual(["public, max-age=31536000, immutable"]);
      expect(cacheControl(t, "/fonts/a.woff2")).toEqual(["public, max-age=31536000, immutable"]);
    }
  });

  it("the app rewrite takes routes, never files", () => {
    for (const t of targets) {
      const rewrite = (p: string) => t.rewrites.some((r) => matches(r, p) && r.destination === "/index.html");
      for (const p of ["/", "/read/abc_-1", "/welcome", "/connect", "/v2", "/profile"]) expect(rewrite(p), p).toBe(true);
      for (const p of ["/assets/x.js", "/fonts/a.woff2", "/favicon.svg"]) expect(rewrite(p), p).toBe(false);
    }
  });
});
