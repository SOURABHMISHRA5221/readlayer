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
