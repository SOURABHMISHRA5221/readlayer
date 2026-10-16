import type { MouseEvent, ReactNode, Ref } from "react";

import { Margo, type MargoMood } from "../components/Margo";
import { Segmented } from "../components/Segmented";
import { Wordmark } from "../components/Wordmark";
import type { PersonaKey } from "../lib/personas";
import { navigate } from "../lib/router";
import note from "./demoNoteStatic.json";
import evals from "./evals.json";
import { paragraph, site } from "./demoParagraph.json";
import { DEFAULT_DEMO_PERSONA, DEMO_PERSONAS } from "./demoPersonas";
import { CHIPS } from "./formats";
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
  /** Where the annotator puts the open note (live demo only). */
  noteRef?: Ref<HTMLDivElement>;
  /** The first paint's copy of the note, hidden once the live one is in (live demo only). */
  staticNoteRef?: Ref<HTMLDivElement>;
}

/**
 * The demo card (decision 46): opens on the payoff, with the default persona's note already
 * open under the paragraph and Margo handing it over. The note slot has one fixed height that
 * the static copy and the live card both fill, so the swap moves nothing.
 */
export function DemoFrame({ persona, onPersona, paragraphRef, noteRef, staticNoteRef }: DemoFrameProps) {
  return (
    <figure className="lp-demo">
      <div className="lp-demo__toggle">
        <Segmented label="View as:" options={DEMO_PERSONAS} value={persona} onChange={onPersona} />
      </div>
      <div className="lp-demo__sheet">
        <p className="lp-demo__source">From {site} · real paragraph, real notes; the words are unchanged</p>
        <p className="lp-demo__para" data-rl-paragraph={paragraph.id} ref={paragraphRef}>
          {paragraph.text}
        </p>
        <div className="lp-demo__note" data-rl-ui="">
          <MargoHero className="lp-demo__margo" mood={PERSONA_MOOD[persona]} />
          <DemoNoteStatic ref={staticNoteRef} />
          <div className="lp-demo__note-live" ref={noteRef} />
        </div>
      </div>
    </figure>
  );
}

const PITCH_UNAWARE = "New to you, so this note starts from zero";

/**
 * The default persona's open note as plain markup, for the first paint before the annotator
 * loads (strings match the annotator's card; a vitest checks). Inert and aria-hidden: the live
 * card replaces it within a frame of being ready.
 */
function DemoNoteStatic({ ref }: { ref?: Ref<HTMLDivElement> }) {
  return (
    <div className="lp-note-static" ref={ref} aria-hidden="true">
      <div className="lp-note-static__body">
        <p className="lp-note-static__domain">{note.domain}</p>
        <p className="lp-note-static__title">{note.label}</p>
        <p className="lp-note-static__pitch">
          <span className="lp-note-static__meter">
            <span />
            <span />
            <span />
            <span />
          </span>
          {PITCH_UNAWARE}
        </p>
        <div className="lp-note-static__bg">
          <p className="lp-note-static__label">
            Background <span className="lp-note-static__frame">Analogy · {note.analogy_domain}</span>
          </p>
          <p className="lp-note-static__text">{note.background}</p>
        </div>
        <div className="lp-note-static__says">
          <p className="lp-note-static__label">What the author is saying</p>
          <p className="lp-note-static__quote">{note.author_says}</p>
        </div>
      </div>
      <div className="lp-note-static__foot">
        <span className="lp-note-static__btn">Try it on any article</span>
        <span className="lp-note-static__card-label">Explanation — not the author's words</span>
      </div>
    </div>
  );
}

/** The what and why beside the demo (decision 46b): Sourabh's three lines, each with a Margo face. */
const VALUES: { mood: MargoMood; lead: string; rest: string }[] = [
  { mood: "think", lead: "Notes only on what you'd miss.", rest: "Gloss knows what you already know, and skips it." },
  { mood: "happy", lead: "Explained in your world.", rest: "Software, cricket, law: analogies from what you understand." },
  { mood: "idle", lead: "Never changes the original.", rest: "Every note is checked against the article before you see it." },
];

function Values() {
  return (
    <ul className="lp-values">
      {VALUES.map((v) => (
        <li key={v.lead} className="lp-values__item">
          <Margo mood={v.mood} size={24} className="lp-values__face" />
          <p>
            <strong>{v.lead}</strong> {v.rest}
          </p>
        </li>
      ))}
    </ul>
  );
}

/** The verifier's results from evals.json, never rounded; links to the trust band. */
function Proof({ where }: { where: "wide" | "narrow" }) {
  const { adversarial: bad, good } = evals;
  return (
    <p className={`lp-proof lp-proof--${where}`}>
      <a href="#how-we-test">
        {bad.passed}/{bad.total} misleading notes caught · {good.passed}/{good.total} faithful notes passed in our tests
      </a>
    </p>
  );
}

/** "Read with Gloss:" (decision 46c, 61): the formats as chips, honest about which get notes. */
function ReadWith() {
  return (
    <div className="lp-readwith">
      <span className="lp-readwith__label">Open with Gloss:</span>
      <ul className="lp-readwith__chips">
        {CHIPS.map((c) => (
          <li key={c.label} className={`lp-chip${c.notes ? " lp-chip--notes" : ""}`}>
            {c.label}
            {c.notes && <span className="visually-hidden">, with notes</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The calls to action, shared by the bar, the hero and the final section (inert in the static paint). */
interface Actions {
  onDemo?: () => void;
  onGoogle?: () => void;
  busy?: "demo" | "google" | null;
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
  /** The bar's Sign in and Try the demo (the hero's own handlers). */
  actions?: Actions;
}

const openPrivacy = (e: MouseEvent<HTMLAnchorElement>) => {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  navigate("/privacy");
};

export function Hero({ themeToggle, demo, ctas, notice, children, footer, actions = {} }: HeroProps) {
  const { onDemo = noop, onGoogle = noop, busy = null } = actions;
  return (
    <>
      <header className="lp-bar">
        <Wordmark size="lg" />
        <nav className="lp-nav" aria-label="Main">
          <a className="lp-nav__link lp-nav__link--wide" href="#how-it-works">
            How it works
          </a>
          <a className="lp-nav__link lp-nav__link--wide" href="/privacy" onClick={openPrivacy}>
            Privacy
          </a>
          <button type="button" className="lp-nav__link" onClick={onGoogle} disabled={busy !== null}>
            Sign in
          </button>
          <button type="button" className="btn btn--primary lp-nav__cta" onClick={onDemo} disabled={busy !== null}>
            Try the demo
          </button>
          <div className="lp-bar__end">{themeToggle}</div>
        </nav>
      </header>
      <main className="lp-main">
        <section className="lp-hero" aria-labelledby="lp-hero-title">
          <div className="lp-hero__copy">
            {notice}
            <h1 id="lp-hero-title" className="lp-hero__title">
              Consume anything. <span className="lp-hero__mark">Understand all of it.</span>
            </h1>
            <p className="lp-hero__sub">
              Gloss explains the parts you'd miss, in words you already know, without changing a word of the original.
            </p>
            <Values />
            <Proof where="wide" />
            {ctas ?? <HeroCtas />}
            <ReadWith />
          </div>
          {demo ?? <DemoFrame persona={DEFAULT_DEMO_PERSONA} onPersona={noop} />}
          <Proof where="narrow" />
        </section>
        {children}
      </main>
      {footer}
    </>
  );
}

interface HeroCtasProps extends Actions {
  error?: string | null;
}

export function HeroCtas({ onDemo = noop, onGoogle = noop, busy = null, error = null }: HeroCtasProps) {
  return (
    <div className="lp-ctas">
      <div className="lp-ctas__row">
        <button type="button" className="btn btn--primary lp-cta" onClick={onDemo} disabled={busy !== null}>
          {busy === "demo" ? "Starting…" : "Try it as a demo consumer"}
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
