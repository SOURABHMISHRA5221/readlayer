import { mount, type AnnotatorEvent, type CardAnnotation } from "@readlayer/annotator";
import { useEffect, useState, type RefObject } from "react";

export interface AnnotatorState {
  resolved: number;
  unresolved: number;
}

const logEvent = (event: AnnotatorEvent) => {
  // Events go to the console until POST /v1/events exists (M3).
  console.info("[readlayer] event", event);
};

/** Mounts the shared annotator over the rendered article; remounts when annotations change. */
export function useAnnotator(
  root: RefObject<HTMLElement | null>,
  annotations: CardAnnotation[] | null,
): AnnotatorState | null {
  const [state, setState] = useState<AnnotatorState | null>(null);
  useEffect(() => {
    const el = root.current;
    if (!el || !annotations) return;
    const mounted = mount(el, annotations, { onEvent: logEvent });
    setState({ resolved: mounted.resolved.length, unresolved: mounted.unresolved.length });
    if (mounted.unresolved.length) {
      console.warn("[readlayer] anchors not found", mounted.unresolved);
    }
    return () => {
      mounted.destroy();
      setState(null);
    };
  }, [root, annotations]);
  return state;
}
