import type { ReactNode, Ref } from "react";

import { Segmented } from "../components/Segmented";
import { Wordmark } from "../components/Wordmark";
import type { PersonaKey } from "../lib/personas";
import { paragraph, site } from "./demoParagraph.json";
import { DEFAULT_DEMO_PERSONA, DEMO_PERSONAS } from "./demoPersonas";
import { MargoHero, PERSONA_MOOD } from "./MargoHero";

/**
 * The landing hero (plan A2). `HeroStatic` is also copied into index.html, so the first paint is
 * these exact pixels; React then renders the same markup while auth loads, the landing chunk
 * replaces it with the live version, and the demo mounts into the same fixed box. A vitest keeps
 * index.html in step with `HeroStatic` (UPDATE_HERO=1 rewrites it).
 */

const noop = () => undefined;

interface DemoFrameProps {
  persona: PersonaKey;
  onPersona: (key: PersonaKey) => void;
  /** The paragraph the annotator marks (live demo only). */
  paragraphRef?: Ref<HTMLParagraphElement>;
}

export function DemoFrame({ persona, onPersona, paragraphRef }: DemoFrameProps) {
  return (
    <figure className="lp-demo">
      <div className="lp-demo__head">
        <div className="lp-demo__toggle">
          <Segmented label="Read as" options={DEMO_PERSONAS} value={persona} onChange={onPersona} />
        </div>
        <MargoHero className="lp-demo__margo" mood={PERSONA_MOOD[persona]} />
      </div>
      <div className="lp-demo__sheet">
        <p className="lp-demo__source">From {site}</p>
        <p className="lp-demo__para" data-rl-paragraph={paragraph.id} ref={paragraphRef}>
          {paragraph.text}
        </p>
      </div>
      <figcaption className="lp-demo__caption">A real paragraph and real notes. Tap a highlighted term.</figcaption>
    </figure>
  );
}

interface HeroProps {
  /** The live parts, from the landing chunk; absent in the static first paint. */
  themeToggle?: ReactNode;
  demo?: ReactNode;
  ctas?: ReactNode;
  notice?: ReactNode;
  /** The rest of the landing: more sections in the same <main>, then the footer. */
  children?: ReactNode;
  footer?: ReactNode;
}

export function Hero({ themeToggle, demo, ctas, notice, children, footer }: HeroProps) {
  return (
    <>
      <header className="lp-bar">
        <Wordmark size="lg" />
        <div className="lp-bar__end">{themeToggle}</div>
      </header>
      <main className="lp-main">
        <section className="lp-hero" aria-labelledby="lp-hero-title">
          <div className="lp-hero__copy">
            {notice}
            <h1 id="lp-hero-title" className="lp-hero__title">
              Read anything. <span className="lp-hero__mark">Understand all of it.</span>
            </h1>
            <p className="lp-hero__sub">
              Gloss explains the parts you'd miss, in words you already know, without changing a word of the original.
            </p>
            {ctas ?? <HeroCtas />}
          </div>
          {demo ?? <DemoFrame persona={DEFAULT_DEMO_PERSONA} onPersona={noop} />}
        </section>
        {children}
      </main>
      {footer}
    </>
  );
}

interface HeroCtasProps {
  onDemo?: () => void;
  onGoogle?: () => void;
  busy?: "demo" | "google" | null;
  error?: string | null;
}

export function HeroCtas({ onDemo = noop, onGoogle = noop, busy = null, error = null }: HeroCtasProps) {
  return (
    <div className="lp-ctas">
      <div className="lp-ctas__row">
        <button type="button" className="btn btn--primary lp-cta" onClick={onDemo} disabled={busy !== null}>
          {busy === "demo" ? "Starting…" : "Try it as a demo reader"}
        </button>
        <button type="button" className="btn lp-cta" onClick={onGoogle} disabled={busy !== null}>
          {busy === "google" ? "Opening Google…" : "Sign in with Google"}
        </button>
      </div>
      <p className="lp-ctas__fine">The demo needs no account, and ending it deletes what it recorded.</p>
      {error && (
        <p className="lp-ctas__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** The first paint: identical to index.html's static hero (hidden there when booting the shell). */
export function HeroStatic() {
  return (
    <div className="lp lp--static">
      <Hero />
    </div>
  );
}
