import type { Band, EditPreview } from "./profileApi";
import { domainLabel } from "./format";

/** Plain-language helpers for the profile page (pure; unit-tested). */

const EVIDENCE: Record<string, string> = {
  knew_this: "You tapped Knew this",
  explain_opened: "You opened an explanation",
  explain_helpful: "You found an explanation helpful",
  text_searched: "You looked it up",
  correction: "You corrected it yourself",
  calibration_answer: "You answered a quick check",
  liked_article_mention: "It was in an article you liked",
  profile_edit_concept: "From your profile edit",
  profile_edit_domain: "From your profile edit",
  report_wrong: "You reported an explanation",
  seed: "Part of this sample reader's starting point",
};

export function evidenceText(type: string, at: string, locale = "en-GB"): string {
  const what = EVIDENCE[type] ?? "Reading activity";
  const when = new Date(at).toLocaleDateString(locale, { day: "numeric", month: "short" });
  return `${what} · ${when}`;
}

export const BAND_LABEL: Record<Band, string> = {
  unaware: "New to you",
  "heard of": "Heard of",
  understands: "Understands",
  "can explain": "Can explain",
};

/** A shape cue for each band, so colour is never the only signal. */
export const BAND_GLYPH: Record<Band, string> = {
  unaware: "○",
  "heard of": "◔",
  understands: "◑",
  "can explain": "●",
};

/** θ on the fixed −2..2 scale → 0..100 for a bar; text always carries the number too. */
export function thetaPercent(theta: number): number {
  return Math.round(((Math.max(-2, Math.min(2, theta)) + 2) / 4) * 100);
}

/** The word for an ability, judged on the value as shown (one decimal), so "0.0" never says
 * "building". */
export function thetaWord(theta: number): string {
  const shown = Math.round(theta * 10) / 10;
  if (shown >= 1) return "advanced";
  if (shown >= 0) return "comfortable";
  if (shown >= -1) return "building";
  return "new";
}

/** "+0.6", "0.0", "−1.5": one decimal, a real minus sign, no "−0.0". */
export function thetaText(theta: number): string {
  const shown = Math.round(theta * 10) / 10;
  if (shown === 0) return "0.0";
  return shown > 0 ? `+${shown.toFixed(1)}` : `−${Math.abs(shown).toFixed(1)}`;
}

const SETTING_LABEL: Record<string, string> = {
  thinks_in: "Analogies from",
  explanation_style: "Explanation length",
  density: "Notes",
  learning_paused: "Learning paused",
};

function show(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return value === null || value === undefined || value === "" ? "none" : String(value);
}

/** One line per change in a profile-edit preview. */
export function previewLines(p: EditPreview["preview"]): string[] {
  const lines: string[] = [];
  for (const d of p.domains) lines.push(`${d.domain}: ability ${d.before.toFixed(1)} → ${d.after.toFixed(1)}`);
  if (p.known.length) lines.push(`${p.known.length} concept${p.known.length > 1 ? "s" : ""} marked as known`);
  if (p.unknown.length) lines.push(`${p.unknown.length} concept${p.unknown.length > 1 ? "s" : ""} marked as new to you`);
  for (const s of p.settings) lines.push(`${SETTING_LABEL[s.setting] ?? s.setting}: ${show(s.before)} → ${show(s.after)}`);
  for (const i of p.interests ?? []) {
    lines.push(`${i.direction === "more" ? "More" : "Less"} ${domainLabel(i.domain) ?? i.domain} in your feed`);
  }
  return lines;
}
