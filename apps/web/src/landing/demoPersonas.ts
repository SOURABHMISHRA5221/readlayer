import type { PersonaKey } from "../lib/personas";

/**
 * The landing demo's "Read as" toggle (plan A4): each label names the persona's analogy frame,
 * and the key is the demo persona the CTA signs in as. demo.json carries the same labels; a
 * vitest keeps them in step.
 */
export const DEMO_PERSONAS: readonly { key: PersonaKey; label: string }[] = [
  { key: "newcomer", label: "Software engineer" },
  { key: "trader", label: "Cricket fan" },
  { key: "policy_student", label: "Policy student" },
];

export const DEFAULT_DEMO_PERSONA: PersonaKey = "newcomer";

/**
 * The note the hero demo opens for each persona (decision 46): the first with an analogy,
 * preferring "bps" (d6). The Cricket fan's bps is a refresher without one, so it opens "tighter
 * policy" (d7). A vitest checks each id exists in demo.json with an analogy.
 */
export const FEATURED_NOTE: Readonly<Record<PersonaKey, string>> = {
  newcomer: "d6",
  trader: "d7",
  policy_student: "d6",
};
