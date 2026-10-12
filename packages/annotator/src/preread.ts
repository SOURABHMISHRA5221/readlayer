/**
 * Pre-read card (DESIGN §6.4): the prerequisites to meet before this article, most basic first.
 * Framework-free so the extension can show it too. Text only: nothing is parsed as HTML.
 */

import { injectStyles, type StyleMode } from "./styles";
import type { PrereadAnnotation, PrereadStep } from "./types";

export const PREREAD_HEADING = "Before you read";
const P = "rl-preread";

export interface PrereadOptions {
  /** Where a step's library explainer lives; the web app routes it, the extension links out. */
  href: (step: PrereadStep) => string;
  /** A step's explainer link was followed (hosts may navigate client-side and log it). */
  onOpen?: (step: PrereadStep, event: MouseEvent) => void;
  /** "external": the host has applied ANNOTATOR_CSS itself (the extension); no <style>. */
  styles?: StyleMode;
}

export interface PrereadHandle {
  destroy(): void;
}

let prereadCount = 0;

export function renderPreread(
  container: HTMLElement,
  item: PrereadAnnotation,
  options: PrereadOptions,
): PrereadHandle {
  const doc = container.ownerDocument;
  injectStyles(doc, options.styles);
  // A known step (where the path starts from) is never presented as "meet this first".
  const steps = item.steps.filter((s) => !s.known);
  const id = `${P}-${++prereadCount}`;
  const section = doc.createElement("section");
  section.className = P;
  section.setAttribute("aria-labelledby", `${id}-title`);

  const heading = doc.createElement("h2");
  heading.className = `${P}__title`;
  heading.id = `${id}-title`;
  heading.textContent = PREREAD_HEADING;
  const lede = doc.createElement("p");
  lede.className = `${P}__lede`;
  lede.textContent =
    steps.length > 1
      ? `This piece assumes ${item.label}. These build up to it, most basic first.`
      : `This piece assumes ${item.label}.`;

  const list = doc.createElement("ol");
  list.className = `${P}__steps`;
  for (const step of steps) list.append(stepItem(doc, step, options));

  section.append(heading, lede, list);
  container.append(section);
  return { destroy: () => section.remove() };
}

function stepItem(doc: Document, step: PrereadStep, options: PrereadOptions): HTMLLIElement {
  const li = doc.createElement("li");
  li.className = `${P}__step`;
  if (step.content_id) {
    const a = doc.createElement("a");
    a.className = `${P}__link`;
    a.href = options.href(step);
    const label = doc.createElement("span");
    label.className = `${P}__label`;
    label.textContent = step.label;
    a.append(label);
    if (step.title) {
      const via = doc.createElement("span");
      via.className = `${P}__via`;
      via.textContent = step.title;
      a.append(via);
    }
    a.addEventListener("click", (e) => options.onOpen?.(step, e));
    li.append(a);
    return li;
  }
  const details = doc.createElement("details");
  details.className = `${P}__details`;
  const summary = doc.createElement("summary");
  summary.className = `${P}__label`;
  summary.textContent = step.label;
  const definition = doc.createElement("p");
  definition.className = `${P}__definition`;
  definition.textContent = step.definition;
  details.append(summary, definition);
  li.append(details);
  return li;
}
