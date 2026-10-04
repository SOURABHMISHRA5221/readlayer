/** Demo personas mirror app/scoring/placeholder.py (PLACEHOLDER until the reader model, M4). */
export const PERSONAS = [
  {
    key: "newcomer",
    label: "Newcomer",
    blurb: "A software engineer. New to economics and finance.",
  },
  {
    key: "trader",
    label: "Trader",
    blurb: "Fluent in markets and business. Policy is a blind spot.",
  },
  {
    key: "policy_student",
    label: "Policy student",
    blurb: "At home in economics and policy. Markets jargon is new.",
  },
] as const;

export type PersonaKey = (typeof PERSONAS)[number]["key"];

export const DENSITIES = [
  { key: "minimal", label: "Minimal" },
  { key: "balanced", label: "Balanced" },
  { key: "guided", label: "Guided" },
] as const;

export type Density = (typeof DENSITIES)[number]["key"];

export function parsePersona(value: string | null): PersonaKey {
  return PERSONAS.find((p) => p.key === value)?.key ?? "newcomer";
}

export function parseDensity(value: string | null): Density {
  return DENSITIES.find((d) => d.key === value)?.key ?? "balanced";
}
