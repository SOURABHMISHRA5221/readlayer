import type { AnnotatorEvent, Explanation } from "@readlayer/annotator";

/** Message protocol between the popup, the content script, the worker and the web app. */

export type Density = "minimal" | "balanced" | "guided";
export const DENSITIES: readonly Density[] = ["minimal", "balanced", "guided"];
export const PERSONAS = [
  { key: "newcomer", label: "Newcomer" },
  { key: "trader", label: "Trader" },
  { key: "policy_student", label: "Policy student" },
] as const;
export type PersonaKey = (typeof PERSONAS)[number]["key"];

/** From the web app's Connect page (chrome.runtime.sendMessage to our id). */
export type ExternalMessage =
  | { type: "ping" }
  | {
      type: "connect";
      idToken: string;
      refreshToken: string;
      expiresAt: number;
      /** The web app's Firebase web API key (public), for refreshing the token. */
      apiKey: string;
      persona?: PersonaKey | null;
    }
  | { type: "disconnect" };

export interface Status {
  connected: boolean;
  demo: boolean;
  name: string | null;
  persona: PersonaKey | null;
  density: Density;
  /** Google readers: onboarding finished (null when unknown, e.g. offline). */
  onboarded: boolean | null;
}

export type ReadResult =
  | { ok: true; already: boolean }
  | { ok: false; reason: "signed_out" | "onboarding" | "refused" | "no_article" | "error"; message: string };

export type PopupMessage =
  | { type: "status" }
  | { type: "read"; tabId: number }
  | { type: "settings"; persona?: PersonaKey; density?: Density };

/** One API step the content script asks the worker to make (the worker holds the token). */
export type ApiOp =
  | { op: "submit"; url: string; title: string; paragraphs: string[] }
  | { op: "analyse"; id: string }
  | { op: "grow"; id: string }
  | { op: "detail"; id: string }
  | { op: "annotations"; id: string; refresh?: boolean }
  | { op: "explain"; id: string; target: { demand_id: string } | { paragraph_id: string } }
  | { op: "events"; events: ReaderEvent[] }
  | { op: "answer"; concept_id: string; known: boolean }
  | { op: "report"; explanation_id: string; content_id: string; concept_id: string | null };

export type ContentMessage = { type: "api"; call: ApiOp };

export type ApiReply<T = unknown> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: string; message: string };

export interface ReaderEvent {
  id: string;
  type: AnnotatorEvent["type"];
  at: string;
  concept_id: string | null;
  content_id: string;
  paragraph_id?: string;
  words?: number;
  ms?: number;
}

export type { Explanation };
