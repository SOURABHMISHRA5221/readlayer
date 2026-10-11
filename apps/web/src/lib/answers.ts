/**
 * "Know this?" answers (DESIGN §6.5, decision 46d): the reader's word is saved to their graph,
 * then the article's notes are refetched so the marks change in place. "Not really" inks the term
 * in as a note, "Yes" removes its mark; no page reload. The short wait lets "Noted, thanks." show
 * before the chip gives way to the new marks.
 */
export const REFRESH_AFTER_ANSWER_MS = 1200;

interface AnswerSteps {
  /** PATCH /v1/me/graph; a rejection reaches the chip, which offers a retry. */
  save: () => Promise<void>;
  /** Refetch the article's annotations and hand them to the annotator. */
  refresh: () => Promise<void>;
  waitMs?: number;
}

export async function answerAndRefresh({ save, refresh, waitMs = REFRESH_AFTER_ANSWER_MS }: AnswerSteps): Promise<void> {
  await save();
  setTimeout(() => {
    // The answer is already saved; a failed refresh keeps the current marks until the next load.
    refresh().catch((e: unknown) => console.warn("[readlayer] notes refresh after an answer failed", e));
  }, waitMs);
}

/** After an answer the page shows no new "Know this?" (one per article view, DESIGN §6.5): the
 * API already leaves it out with refresh=1; this keeps it out whatever the response says. */
export function withoutPrompts<T extends { kind: string }>(extras: readonly T[]): T[] {
  return extras.filter((e) => e.kind !== "prompt");
}
