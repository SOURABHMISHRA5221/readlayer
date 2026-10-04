import type { RefObject } from "react";

import { useScrolled } from "../hooks/useScrolled";
import { DENSITIES, type Density, type PersonaKey } from "../lib/personas";
import { navigate } from "../lib/router";
import { ArrowLeft } from "./Icons";
import { PersonaPicker } from "./PersonaPicker";
import { ProgressBar } from "./ProgressBar";
import { Segmented } from "./Segmented";
import { ThemeToggle } from "./ThemeToggle";
import { Wordmark } from "./Wordmark";

interface ReaderBarProps {
  persona: PersonaKey;
  density: Density;
  onPersona: (key: PersonaKey) => void;
  onDensity: (key: Density) => void;
  libraryHref: string;
  article: RefObject<HTMLElement | null>;
  debug: boolean;
}

export function ReaderBar({ persona, density, onPersona, onDensity, libraryHref, article, debug }: ReaderBarProps) {
  const scrolled = useScrolled();
  return (
    <header className="bar" data-scrolled={scrolled}>
      <div className="bar__inner">
        <div className="bar__lead">
          <a
            className="bar__back"
            href={libraryHref}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
              e.preventDefault();
              navigate(libraryHref);
            }}
          >
            <ArrowLeft size={16} />
            <span>Library</span>
          </a>
          <span className="bar__divider" aria-hidden="true" />
          <Wordmark />
          {debug && <span className="bar__debug">debug</span>}
        </div>
        <div className="bar__controls">
          <PersonaPicker value={persona} onChange={onPersona} />
          <Segmented label="Notes" options={DENSITIES} value={density} onChange={onDensity} />
        </div>
        <div className="bar__end">
          <ThemeToggle />
        </div>
      </div>
      <ProgressBar target={article} />
    </header>
  );
}
