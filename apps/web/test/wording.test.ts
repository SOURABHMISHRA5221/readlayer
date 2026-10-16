// Decision 67 (R4): the UI says "consumer", never "reader", and the mascot isn't named "Margo".
// Walks the web app (except the /v2 concept) and the annotator with the TypeScript compiler API
// and flags user-visible text. Skipped by node kind: className values, import/export specifiers,
// property-name keys, type literals and comments. String literals with no whitespace are code
// (route keys, CSS classes, modes), except in alt / aria-label / title / placeholder, which are
// always checked. A line ending in `// wording-ok: <reason>` is allowed.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..", "..", "..");
const DIRS = [join(ROOT, "apps/web/src"), join(ROOT, "packages/annotator/src")];
const SKIP_DIRS = [join(ROOT, "apps/web/src/landing/v2")];
const BANNED = /\breaders?\b|\bMargo\b/i;
const VISIBLE_ATTRS = new Set(["alt", "aria-label", "title", "placeholder"]);

function files(dir: string): string[] {
  if (SKIP_DIRS.includes(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(name) && !name.endsWith(".d.ts") ? [path] : [];
  });
}

function attrName(node: ts.Node): string | null {
  let p: ts.Node | undefined = node.parent;
  while (p && !ts.isJsxAttribute(p)) {
    if (ts.isJsxElement(p) || ts.isJsxSelfClosingElement(p) || ts.isSourceFile(p)) return null;
    p = p.parent;
  }
  return p ? p.name.getText() : null;
}

function isCode(node: ts.Node): boolean {
  const parent = node.parent;
  if (ts.isImportDeclaration(parent) || ts.isExportDeclaration(parent)) return true;
  if (ts.isImportTypeNode(parent.parent ?? parent) || ts.isExternalModuleReference(parent)) return true;
  if (ts.isLiteralTypeNode(parent)) return true;
  if ((ts.isPropertyAssignment(parent) || ts.isPropertySignature(parent)) && parent.name === node) return true;
  if (ts.isElementAccessExpression(parent) && parent.argumentExpression === node) return true;
  return attrName(node) === "className";
}

function findings(path: string): string[] {
  const text = readFileSync(path, "utf8");
  const lines = text.split("\n");
  const kind = path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind);
  const out: string[] = [];
  const visit = (node: ts.Node) => {
    let value: string | null = null;
    if (ts.isJsxText(node)) value = node.text;
    else if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    ) {
      if (!isCode(node)) {
        const attr = attrName(node);
        const raw = node.text;
        if ((attr && VISIBLE_ATTRS.has(attr)) || /\s/.test(raw)) value = raw;
      }
    }
    if (value && BANNED.test(value)) {
      const line = sf.getLineAndCharacterOfPosition(node.getStart()).line;
      if (!/\/\/\s*wording-ok:/.test(lines[line] ?? "")) {
        out.push(`${relative(ROOT, path)}:${line + 1}: ${value.trim().slice(0, 90)}`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

describe("UI wording (decision 67)", () => {
  it('says "consumer" and never names Margo in visible text', () => {
    const all = DIRS.flatMap(files).flatMap(findings);
    expect(all).toEqual([]);
  });
});
