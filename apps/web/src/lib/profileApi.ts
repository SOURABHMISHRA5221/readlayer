import { api, type RecFormat } from "./api";
import type { Country } from "./country";
import type { PersonaKey } from "./personas";
import type { Domain } from "./taxonomy";

export { DOMAINS, type Domain } from "./taxonomy";

/** Reading profile, onboarding and profile edits (DESIGN §8, §15; M7). */

export type Band = "unaware" | "heard of" | "understands" | "can explain";
export type Level = "new" | "some" | "comfortable" | "expert";
export type ExplanationStyle = "short" | "normal" | "detailed";
export type Density = "minimal" | "balanced" | "guided";
export const FRAMES = [
  "software", "engineering", "science", "medicine", "law", "design", "teaching", "music",
  "cooking", "cricket", "football", "gaming",
] as const; // prettier-ignore
export type Frame = (typeof FRAMES)[number];
export const FIELDS = [
  "software", "finance", "commerce", "law", "science", "medicine", "design", "teaching", "other",
] as const; // prettier-ignore
export type Field = (typeof FIELDS)[number];
/** A field suggests an analogy frame; the reader's pick is what's saved. */
export const FIELD_FRAME: Partial<Record<Field, Frame>> = {
  software: "software", law: "law", science: "science", medicine: "medicine", design: "design",
  teaching: "teaching",
}; // prettier-ignore

export interface Onboarding {
  consented: boolean;
  done: boolean;
  step: "consent" | "onboarding" | "discover" | "calibration" | "done";
  field?: Field | null;
  interests?: Domain[];
  formats?: RecFormat[]; // decision 68
  redo?: "about" | "discover" | null; // Redo setup in progress (decision 48)
  consent_version?: string | null;
}

export interface Profile {
  summary: { text: string; top_domain: string | null; moved_up_this_week: number; learning_paused: boolean };
  /** `rated`: the reader rated, reads in, or has concepts in this domain. */
  domains: { domain: Domain; theta: number; interest: number; rated: boolean; concepts: number; known?: number }[];
  thinks_in: Frame[];
  week: {
    moved_up: { concept_id: string; label: string; from: Band; to: Band; domain?: Domain }[];
    trend: { week: string; annotations_per_1000_words: number }[];
  };
  settings: { density: Density; explanation_style: ExplanationStyle; country?: Country | null };
  persona: PersonaKey | null;
  onboarding: Onboarding;
}

export interface GraphNode {
  id: string;
  label: string;
  domain: Domain;
  band: Band;
  evidence_count: number;
  last_seen: string | null;
  depth: number;
  recent: { type: string; at: string }[];
}

/** All-domains map (Design pass A5). */
export interface OverviewNode {
  id: string;
  label: string;
  domain: Domain;
  band: Band;
  ready: boolean;
  goal: boolean;
  weight: number;
  definition: string;
  recent: { type: string; at: string }[];
  rose_this_week: boolean;
}

export interface Overview {
  view: "overview";
  domains: Domain[];
  nodes: OverviewNode[];
  edges: { from: string; to: string }[];
}

export interface Subgraph {
  nodes: GraphNode[];
  edges: { from: string; to: string }[];
  truncated: boolean;
}

export interface CalibrationNext {
  done: boolean;
  asked: number;
  total: number;
  item?: { concept_id: string; label: string; domain: Domain };
}

export interface CalibrationSet {
  done: boolean;
  total: number;
  items: { concept_id: string; label: string; domain: Domain; answered: boolean }[];
}

export interface EditPreview {
  edit_id: string;
  persona: PersonaKey | null;
  expires_in_s: number;
  preview: {
    domains: { domain: Domain; before: number; after: number }[];
    known: { concept_id: string; label: string }[];
    unknown: { concept_id: string; label: string }[];
    settings: { setting: string; before: unknown; after: unknown }[];
    interests?: { domain: Domain; direction: "more" | "less" }[]; // decision 48
    unresolved: string[];
    note?: string | null;
  };
}

export interface EditSummary {
  edit_id: string;
  status: "applied" | "undone";
  persona: PersonaKey | null;
  applied_at: string | null;
  concepts: number;
  domains: string[];
  settings: string[];
  interests?: { domain: Domain; direction: "more" | "less" }[]; // decision 48
}

const q = (persona: PersonaKey | null, first = true) => (persona ? `${first ? "?" : "&"}persona=${persona}` : "");

/** Reading goals (M7.5 §C). */
export interface GoalTarget {
  concept_id: string;
  label: string;
  known: boolean;
}
/** A previewed learning goal (decision 48): a concept and its chain, or a topic and its ideas. */
export interface GoalPreview {
  type: "learning";
  kind: "concept" | "topic";
  label: string;
  concept_id: string | null;
  topic: Domain | null;
  targets: { concept_id: string; label: string }[];
}
export interface Goal {
  id: string;
  type: "habit" | "learning";
  kind?: "concept" | "topic" | null;
  label: string;
  metric: "articles" | "minutes" | null;
  per_week: number | null;
  targets: GoalTarget[];
  done: number;
  total: number;
  fraction: number;
  paused: boolean;
}

export const profileApi = {
  profile: (persona: PersonaKey | null, signal?: AbortSignal) =>
    api.raw.get<Profile>(`/v1/me/profile${q(persona)}`, signal),
  goals: (signal?: AbortSignal) => api.raw.get<Goal[]>("/v1/me/goals", signal),
  addHabit: (metric: "articles" | "minutes", per_week: number) =>
    api.raw.send<Goal>("POST", "/v1/me/goals", { type: "habit", metric, per_week }),
  addLearning: (text: string) => api.raw.send<Goal>("POST", "/v1/me/goals", { type: "learning", text }),
  /** The text goes in this request only; saving sends the previewed ids, never the text. */
  previewLearning: (text: string) =>
    api.raw.send<GoalPreview>("POST", "/v1/me/goals/preview", { type: "learning", text }),
  saveLearning: (p: GoalPreview) =>
    api.raw.send<Goal>("POST", "/v1/me/goals", {
      type: "learning_resolved",
      kind: p.kind,
      concept_id: p.concept_id,
      topic: p.topic,
      target_ids: p.targets.map((t) => t.concept_id),
    }),
  redo: () => api.raw.send<{ redo: string }>("POST", "/v1/onboarding/redo", {}),
  cancelRedo: () => api.raw.send<{ redo: null }>("POST", "/v1/onboarding/redo/cancel", {}),
  deleteGoal: (id: string) => api.raw.send<null>("DELETE", `/v1/me/goals/${id}`, undefined),
  overview: (persona: PersonaKey | null, signal?: AbortSignal) =>
    api.raw.get<Overview>(`/v1/me/graph?view=overview${q(persona, false)}`, signal),
  goalGraph: (goalId: string, signal?: AbortSignal) =>
    api.raw.get<Subgraph>(`/v1/me/graph?goal=${encodeURIComponent(goalId)}`, signal),
  graph: (persona: PersonaKey | null, domain: Domain, search = "", signal?: AbortSignal) =>
    api.raw.get<Subgraph>(
      `/v1/me/graph?domain=${domain}${search ? `&q=${encodeURIComponent(search)}` : ""}${q(persona, false)}`,
      signal,
    ),
  settings: (
    changes: Partial<{ thinks_in: Frame[]; density: Density; explanation_style: ExplanationStyle; learning_paused: boolean; country: Country }>,
  ) =>
    api.raw.send<Record<string, unknown>>("PATCH", "/v1/me/settings", changes),
  consent: (version: string) => api.raw.send<{ consented: boolean }>("POST", "/v1/me/consent", { version }),
  onboarding: (answers: {
    field: Field;
    interests: Domain[];
    comfort?: Partial<Record<Domain, Level>>;
    thinks_in: Frame[];
    liked_content_ids?: string[];
    country?: Country; // decision 50
    formats?: RecFormat[]; // decision 68: read / watch / listen
  }) => api.raw.send<{ saved: boolean; next: string }>("POST", "/v1/onboarding", answers),
  calibrationNext: () => api.raw.get<CalibrationNext>("/v1/calibration/next"),
  /** Decision 68 K4b: the whole Quick check at once. */
  calibrationSet: () => api.raw.get<CalibrationSet>("/v1/calibration/set"),
  calibrationAnswer: (concept_id: string, answer: "explain" | "heard" | "none") =>
    api.raw.send<{ done: boolean; asked: number }>("POST", "/v1/calibration/answer", { concept_id, answer }),
  calibrationSkip: () => api.raw.send<{ done: boolean }>("POST", "/v1/calibration/skip", {}),
  parseEdit: (text: string, persona: PersonaKey | null) =>
    api.raw.send<EditPreview>("POST", `/v1/me/profile/edits${q(persona)}`, { text }),
  applyEdit: (id: string, persona: PersonaKey | null) =>
    api.raw.send<EditSummary>("POST", `/v1/me/profile/edits/${id}/apply${q(persona)}`, {}),
  undoEdit: (id: string, persona: PersonaKey | null) =>
    api.raw.send<EditSummary>("POST", `/v1/me/profile/edits/${id}/undo${q(persona)}`, {}),
  edits: (persona: PersonaKey | null) =>
    api.raw.get<{ edits: EditSummary[] }>(`/v1/me/profile/edits${q(persona)}`),
  resetDemo: (persona: PersonaKey) =>
    api.raw.send<{ reset: boolean }>("POST", "/v1/me/demo/reset", { persona }),
};
