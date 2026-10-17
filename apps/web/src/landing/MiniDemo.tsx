import { createAnnotator, type Annotator } from "@readlayer/annotator";
import { useEffect, useRef } from "react";

import type { PersonaKey } from "../lib/personas";
import { demoAnnotations, demoExplanation } from "./demoData";
import { FEATURED_NOTE } from "./demoPersonas";
import { DemoFrame } from "./Hero";

interface MiniDemoProps {
  persona: PersonaKey;
  onPersona: (key: PersonaKey) => void;
  /** The card's one action: start the demo as this persona. */
  onTry: () => void;
}

/**
 * The hero's live demo (plan A4, decision 46): the reader's own annotator on one real paragraph,
 * fed from demo.json, with the persona's featured note open in the card (inline mode). No network
 * after load: no onEvent, no depth buttons, and explanations come from the JSON. The toggle calls
 * update(), so only the notes that differ change, then opens that persona's featured note.
 */
export function MiniDemo({ persona, onPersona, onTry }: MiniDemoProps) {
  const paragraph = useRef<HTMLParagraphElement>(null);
  const noteHost = useRef<HTMLDivElement>(null);
  const staticNote = useRef<HTMLDivElement>(null);
  const annotator = useRef<Annotator | null>(null);
  // Read when a card opens or its button is pressed, so neither rebuilds the annotator.
  const personaRef = useRef(persona);
  personaRef.current = persona;
  const onTryRef = useRef(onTry);
  onTryRef.current = onTry;
  // A fast A → B → A toggle must end on A's note: only the latest switch may open one.
  const switchSeq = useRef(0);

  useEffect(() => {
    const root = paragraph.current?.closest<HTMLElement>(".lp-demo__sheet");
    const host = noteHost.current;
    if (!root || !host) return;
    const instance = createAnnotator(root, {
      actions: "demo",
      inline: host,
      demoAction: { label: "Try it on any content", onClick: () => onTryRef.current() },
      loadExplanation: async (a) => {
        const explanation = demoExplanation(personaRef.current, a.id);
        if (!explanation) throw new Error("no demo explanation");
        return explanation;
      },
      // The live card has just been revealed: drop the first paint's copy in the same frame.
      onCardReady: () => {
        if (staticNote.current) staticNote.current.hidden = true;
      },
    });
    annotator.current = instance;
    return () => {
      instance.destroy();
      annotator.current = null;
    };
  }, []);

  useEffect(() => {
    const seq = ++switchSeq.current;
    const instance = annotator.current;
    if (!instance) return;
    void instance.update(demoAnnotations(persona), { reader: persona }).then(() => {
      if (seq === switchSeq.current && annotator.current === instance) instance.open(FEATURED_NOTE[persona]);
    });
  }, [persona]);

  return (
    <DemoFrame
      persona={persona}
      onPersona={onPersona}
      paragraphRef={paragraph}
      noteRef={noteHost}
      staticNoteRef={staticNote}
    />
  );
}
