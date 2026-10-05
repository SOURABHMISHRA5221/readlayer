/** Demo personas mirror app/reader/personas.py: each is a seeded reader graph that learns per demo session. */
export const PERSONAS = [
  {
    key: "newcomer",
    label: "Newcomer",
    short: "Newcomer",
    initials: "NC",
    blurb: "A software engineer meeting economics and finance for the first time.",
    strengths: ["Software", "Business basics"],
  },
  {
    key: "trader",
    label: "Markets trader",
    short: "Trader",
    initials: "MT",
    blurb: "Lives in markets and company results; policy is a blind spot.",
    strengths: ["Finance", "Business"],
  },
  {
    key: "policy_student",
    label: "Policy student",
    short: "Policy",
    initials: "PS",
    blurb: "Reads central banks and budgets for fun; markets jargon is new.",
    strengths: ["Policy", "Economics"],
  },
] as const;

export type Persona = (typeof PERSONAS)[number];
export type PersonaKey = Persona["key"];

export const DENSITIES = [
  { key: "minimal", label: "Minimal" },
  { key: "balanced", label: "Balanced" },
  { key: "guided", label: "Guided" },
] as const;

export type Density = (typeof DENSITIES)[number]["key"];

export const DEFAULT_PERSONA: PersonaKey = "newcomer";
export const DEFAULT_DENSITY: Density = "balanced";

export function parsePersona(value: string | null): PersonaKey {
  return PERSONAS.find((p) => p.key === value)?.key ?? DEFAULT_PERSONA;
}

export function parseDensity(value: string | null): Density {
  return DENSITIES.find((d) => d.key === value)?.key ?? DEFAULT_DENSITY;
}

export function personaOf(key: PersonaKey): Persona {
  return PERSONAS.find((p) => p.key === key) ?? PERSONAS[0];
}

/** The persona a reader views as: demo (anonymous) readers only; signed-in readers are themselves. */
export function readerPersona(url: URL, isDemo: boolean): PersonaKey | null {
  return isDemo ? parsePersona(url.searchParams.get("persona")) : null;
}

/** URL value for a persona: omitted for the default and for signed-in readers. */
export function personaParam(persona: PersonaKey | null): string | null {
  return persona && persona !== DEFAULT_PERSONA ? persona : null;
}
