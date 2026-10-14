const WORDS_PER_MINUTE = 230;

const SOURCE_NAMES: Record<string, string> = {
  "Wikimedia Foundation, Inc.": "Wikipedia",
};

export { DOMAINS, type Domain } from "./taxonomy";

export function sourceName(site: string): string {
  return SOURCE_NAMES[site] ?? (site || "Unknown source");
}

/** Monogram for a source mark from the name's capitals: BusinessLine → BL, BBC News → BBC,
 *  The Economic Times → ET, Mint → M. */
export function sourceMonogram(site: string): string {
  const name = sourceName(site).replace(/^The\s+/i, "");
  const acronym = name.match(/\b[A-Z]{2,4}\b/);
  if (acronym) return acronym[0];
  const capitals = name.match(/[A-Z]/g) ?? [];
  if (capitals.length) return capitals.slice(0, 2).join("");
  return name.slice(0, 1).toUpperCase() || "?";
}

export function readingMinutes(words: number): number {
  return Math.max(1, Math.round(words / WORDS_PER_MINUTE));
}

export const formatCount = (n: number) => n.toLocaleString("en-IN");

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** "2026-10-03" → "3 Oct 2026"; null for anything unparseable. */
export function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : DATE_FORMAT.format(date);
}

/** Publisher author strings use ";" between names. */
export function formatByline(author: string | null): string | null {
  if (!author) return null;
  const names = author
    .split(/\s*;\s*/)
    .map((n) => n.trim())
    .filter(Boolean);
  if (!names.length) return null;
  if (names.length === 1) return names[0] ?? null;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export function domainLabel(domain: string | null): string | null {
  return domain ? domain[0]!.toUpperCase() + domain.slice(1) : null;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${formatCount(n)} ${n === 1 ? one : many}`;
}

/** 760 → "12:40", 3725 → "1:02:05". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** "16 min": the header's length, rounded, at least one minute. */
export function minutes(seconds: number): string {
  return `${Math.max(1, Math.round(seconds / 60))} min`;
}
