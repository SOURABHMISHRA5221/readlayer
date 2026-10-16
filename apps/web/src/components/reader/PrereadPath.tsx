import type { PrereadAnnotation } from "@readlayer/annotator";
import { useId, useState } from "react";

import { personaParam, type PersonaKey } from "../../lib/personas";
import { navigate, withParams } from "../../lib/router";

type Step = PrereadAnnotation["steps"][number] & { known?: boolean };

/** "Before you read" as a path (Design pass A2/C6): known steps ticked, the key idea last. */
interface PrereadPathProps {
  item: PrereadAnnotation;
  persona: PersonaKey | null;
  /** "Before you watch" / "Before you listen" on a transcript. */
  heading?: string;
}

export function PrereadPath({ item, persona, heading = "Before you read" }: PrereadPathProps) { // wording-ok: article format word (watch / listen siblings)
  const [open, setOpen] = useState<string | null>(null);
  const id = useId();
  const steps = item.steps as Step[];
  const unknown = steps.filter((s) => !s.known).length;
  const current = steps[steps.length - 1];
  const href = (cid: string) => withParams(new URL(`/read/${cid}`, window.location.origin), { persona: personaParam(persona) });
  const openStep = steps.find((s) => s.concept_id === open);
  return (
    <section className="path" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="path__h">
        {heading}
      </h2>
      <p className="path__sub">
        {unknown > 1
          ? `This piece leans on ${item.label}. Here's the path to it, most basic first.`
          : `This piece leans on one idea you haven't met yet: ${item.label}.`}
      </p>
      <ol className="path__steps">
        {steps.map((s, i) => (
          <li key={s.concept_id} className="path__item">
            {i > 0 && <span className="path__join" aria-hidden="true" />}
            <button
              type="button"
              className={`path__step${s.known ? " is-known" : ""}${s === current ? " is-current" : ""}`}
              aria-expanded={open === s.concept_id}
              aria-controls={`${id}-def`}
              onClick={() => setOpen(open === s.concept_id ? null : s.concept_id)}
            >
              <span className="path__mark" aria-hidden="true">
                {s.known ? "✓" : steps.filter((x) => !x.known).indexOf(s) + 1}
              </span>
              {s.label}
              <span className="visually-hidden">{s.known ? ", you know this" : s === current ? ", this article's key idea" : ""}</span>
            </button>
          </li>
        ))}
      </ol>
      <div id={`${id}-def`} className="path__def" hidden={!openStep} aria-live="polite">
        {openStep && (
          <>
            <p>{openStep.definition}</p>
            {openStep.content_id && (
              <a
                href={href(openStep.content_id)}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                  e.preventDefault();
                  navigate(href(openStep.content_id ?? ""));
                  window.scrollTo(0, 0);
                }}
              >
                Read the explainer{openStep.title ? `: ${openStep.title}` : ""}
              </a>
            )}
          </>
        )}
      </div>
    </section>
  );
}
