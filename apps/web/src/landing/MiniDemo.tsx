import { createAnnotator, type Annotator } from "@readlayer/annotator";
import { useEffect, useRef } from "react";

import type { PersonaKey } from "../lib/personas";
import { demoAnnotations, demoExplanation } from "./demoData";
import { DemoFrame } from "./Hero";

interface MiniDemoProps {
  persona: PersonaKey;
  onPersona: (key: PersonaKey) => void;
  /** The card's one action: start the demo as this persona. */
  onTry: () => void;
}

/**
 * The hero's live demo (plan A4): the reader's own annotator on one real paragraph, fed from
 * demo.json. No network after load: no onEvent, no depth buttons, and explanations come from the
 * JSON. The toggle calls update(), so only the notes that differ change.
 */
export function MiniDemo({ persona, onPersona, onTry }: MiniDemoProps) {
  const paragraph = useRef<HTMLParagraphElement>(null);
  const annotator = useRef<Annotator | null>(null);
  // Read when a card opens or its button is pressed, so neither rebuilds the annotator.
  const personaRef = useRef(persona);
  personaRef.current = persona;
  const onTryRef = useRef(onTry);
  onTryRef.current = onTry;

  useEffect(() => {
    const root = paragraph.current?.closest<HTMLElement>(".lp-demo__sheet");
    if (!root) return;
    const instance = createAnnotator(root, {
      actions: "demo",
      demoAction: { label: "Try it on any article", onClick: () => onTryRef.current() },
      loadExplanation: async (a) => {
        const explanation = demoExplanation(personaRef.current, a.id);
        if (!explanation) throw new Error("no demo explanation");
        return explanation;
      },
    });
    annotator.current = instance;
    return () => {
      instance.destroy();
      annotator.current = null;
    };
  }, []);

  useEffect(() => {
    void annotator.current?.update(demoAnnotations(persona), { reader: persona });
  }, [persona]);

  return <DemoFrame persona={persona} onPersona={onPersona} paragraphRef={paragraph} />;
}
