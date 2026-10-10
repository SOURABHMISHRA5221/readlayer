/**
 * The "Know this?" chip (DESIGN §6.5): sits right after its term, asks once, and collapses to a
 * quiet confirmation. It is annotator UI, never article text (UI_ATTR).
 */

import type { PromptAnnotation } from "./types";
import { UI_ATTR } from "./ui";

const A = "rl-ask";
export const ASK_QUESTION = "Know this?";
export const ASK_DONE = "Noted, thanks.";
const ASK_RETRY = "Couldn't save that. Try again.";

export type AnswerFn = (prompt: PromptAnnotation, known: boolean) => void | Promise<void>;

export interface Ask {
  el: HTMLElement;
  answered: boolean;
}

export function createAsk(
  doc: Document,
  prompt: PromptAnnotation,
  onAnswer: AnswerFn,
  alreadyAnswered = false,
): Ask {
  const group = doc.createElement("span");
  group.className = A;
  group.setAttribute(UI_ATTR, "");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", `Do you know ${prompt.label}?`);
  group.dataset.rlPrompt = prompt.id;

  const question = doc.createElement("span");
  question.className = `${A}__q`;
  question.textContent = ASK_QUESTION;
  question.setAttribute("aria-hidden", "true"); // the group's label says it

  const yes = choice(doc, "Yes");
  const no = choice(doc, "Not really");
  // Present from the start so the confirmation is announced when it appears.
  const status = doc.createElement("span");
  status.className = `${A}__status`;
  status.setAttribute("aria-live", "polite");
  status.tabIndex = -1;
  group.append(question, yes, no, status);

  const ask: Ask = { el: group, answered: false };
  const done = () => {
    ask.answered = true;
    group.dataset.state = "done";
    question.hidden = yes.hidden = no.hidden = true;
    status.textContent = ASK_DONE;
  };
  if (alreadyAnswered) done();
  const answer = async (known: boolean) => {
    yes.disabled = no.disabled = true;
    try {
      await onAnswer(prompt, known);
      done();
      status.focus({ preventScroll: true });
    } catch {
      yes.disabled = no.disabled = false;
      status.textContent = ASK_RETRY;
    }
  };
  yes.addEventListener("click", () => void answer(true));
  no.addEventListener("click", () => void answer(false));
  return ask;
}

function choice(doc: Document, text: string): HTMLButtonElement {
  const b = doc.createElement("button");
  b.type = "button";
  b.className = `${A}__btn`;
  b.textContent = text;
  return b;
}
