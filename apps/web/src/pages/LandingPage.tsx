import { lazy, Suspense, useEffect, useState } from "react";

import { ThemeToggle } from "../components/ThemeToggle";
import { DEFAULT_DEMO_PERSONA } from "../landing/demoPersonas";
import { demoNotes, noteCount, type DemoNote } from "../landing/demoData";
import { paragraph } from "../landing/demoParagraph.json";
import evals from "../landing/evals.json";
import { Hero, HeroCtas } from "../landing/Hero";
import { Clip, type Focus } from "../landing/Clip";
import focus from "../landing/clipFocus.json";
import { DeviceFrame, SeeItInAction } from "../landing/DeviceFrame";
import { ProblemArt } from "../landing/ProblemArt";
import { MargoHero } from "../landing/MargoHero";
import { GlossInBrowser } from "../landing/Extension";
import { Footer } from "../landing/Footer";
import { FORMATS } from "../landing/formatsFull";
import { MiniDemo } from "../landing/MiniDemo";
import { REPO_URL } from "../landing/links";
import { WatchAndListen } from "../landing/WatchListen";
import { signInError, signInWithGoogle, startDemo } from "../lib/auth";
import { personaParam, type PersonaKey } from "../lib/personas";
import { matchRoute, navigate, rememberReturn, withParams } from "../lib/router";
import "../landing/landing.css";

type Busy = null | "demo" | "google";

/** The faces a note card uses: fetched once the landing is up, so opening a note fetches nothing. */
const CARD_FACES = ["400 16px 'Schibsted Grotesk'", "600 16px 'Schibsted Grotesk'", "700 16px 'Schibsted Grotesk'", "400 16px 'Source Serif 4'", "italic 400 16px 'Source Serif 4'"];

/** /v2: the view-only concept landing (decision 63, docs/plans/landing-v2.md), its own chunk. */
const LandingV2 = lazy(() => import("../landing/v2/LandingV2"));

export default function LandingRoute({ url }: { url: URL }) {
  if (url.pathname === "/v2") {
    return (
      <Suspense fallback={null}>
        <LandingV2 />
      </Suspense>
    );
  }
  return <LandingPage url={url} />;
}

/**
 * The signed-out front door (decision 41, plan A): what Gloss solves, why the usual options fail,
 * how it works and why to trust it, with a live demo and no network after load. A signed-out
 * deep link shows it too, and opens after sign-in.
 */
function LandingPage({ url }: { url: URL }) {
  const [persona, setPersona] = useState<PersonaKey>(DEFAULT_DEMO_PERSONA);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const deepLink = ["reader", "profile", "feed"].includes(matchRoute(url.pathname).name);

  useEffect(() => {
    document.title = "Gloss · Read anything. Understand all of it.";
    rememberReturn(url.pathname);
  }, [url.pathname]);

  useEffect(() => {
    void Promise.all(CARD_FACES.map((f) => document.fonts?.load(f))).catch(() => undefined);
  }, []);

  const google = async () => {
    setBusy("google");
    setError(null);
    try {
      await signInWithGoogle();
    } catch (e) {
      setError(signInError(e));
      setBusy(null);
    }
  };

  const demo = async () => {
    setBusy("demo");
    setError(null);
    // The persona goes in the URL first: the app renders as soon as the session exists.
    navigate(withParams(url, { persona: personaParam(persona) }), { replace: true });
    try {
      await startDemo();
    } catch (e) {
      setError(signInError(e) ?? "The demo didn't start. Try again.");
      setBusy(null);
    }
  };

  const ctas = <HeroCtas onDemo={demo} onGoogle={google} busy={busy} error={error} />;

  return (
    <div className="lp">
      <Hero
        themeToggle={<ThemeToggle />}
        actions={{ onDemo: demo, onGoogle: google, busy }}
        notice={
          deepLink ? (
            <p className="lp-notice" role="status">
              Sign in or try the demo to open that page.
            </p>
          ) : null
        }
        ctas={ctas}
        demo={<MiniDemo persona={persona} onPersona={setPersona} onTry={demo} />}
        footer={<Footer />}
      >
        <SeeItInAction />
        <GlossInBrowser />
        <WatchAndListen />
        <Problem />
        <Solution />
        <HowItWorks />
        <Trust />
        <Formats />
        <section className="lp-final" aria-labelledby="lp-final-title">
          <div className="lp-final__copy">
            <MargoHero mood="happy" className="lp-final__margo" />
            <h2 id="lp-final-title" className="lp-final__title">
              Your next article, explained for you.
            </h2>
            <HeroCtas onDemo={demo} onGoogle={google} busy={busy} />
          </div>
          <figure className="lp-final__map">
            <DeviceFrame kind="laptop">
              <Clip {...MAP_CLIP} focus={FOCUS[MAP_CLIP.name]} />
            </DeviceFrame>
            <figcaption>Your map of what you know fills in as you read.</figcaption>
          </figure>
        </section>
      </Hero>
    </div>
  );
}

function Problem() {
  return (
    <section className="lp-section lp-problem" aria-labelledby="lp-problem-title">
      <header className="lp-problem__head">
        <h2 id="lp-problem-title" className="lp-section__title">
          Everyone reads past something.
        </h2>
        <p className="lp-problem__intro">Three ways a good article loses its consumer.</p>
      </header>
      <ol className="lp-problem__list">
        <li className="lp-problem__item">
          <ProblemArt
            name="jargon"
            alt="The Gloss mascot, a page with a worried face, holds an article with three words highlighted in teal and a question mark above."
          />
          <h3>Jargon and references</h3>
          <p>
            Articles assume you know terms like <i>repo rate</i>, <i>PFAS</i> or <i>Powerplay</i>. Most consumers skip them
            and think they understood.
          </p>
        </li>
        <li className="lp-problem__item">
          <ProblemArt
            name="tabs"
            alt="A dozen browser tabs burst out of a laptop screen while the Gloss mascot looks on, alarmed."
          />
          <h3>Looking things up breaks the flow</h3>
          <p>A new tab, a generic definition written for nobody, and your place in the article is gone.</p>
        </li>
        <li className="lp-problem__item">
          <ProblemArt
            name="shredder"
            alt="A full article page goes into a shredder and only a three-line strip comes out; the Gloss mascot watches, worried."
          />
          <h3>Summaries replace the author</h3>
          <p>
            AI summaries rewrite the article. You lose the author's words, hedges and numbers, and can't tell what was
            invented.
          </p>
        </li>
      </ol>
      <p className="lp-problem__close">Every consumer gets the same article, but no two consumers need the same help.</p>
    </section>
  );
}

/** The demo paragraph with one persona's notes drawn as static highlights. */
function MarkedParagraph({ notes }: { notes: DemoNote[] }) {
  const parts: (string | DemoNote)[] = [];
  let rest = paragraph.text;
  for (const note of notes) {
    const at = rest.indexOf(note.term);
    if (at < 0) continue;
    parts.push(rest.slice(0, at), note);
    rest = rest.slice(at + note.term.length);
  }
  parts.push(rest);
  return (
    <p className="lp-side__para">
      {parts.map((p, i) =>
        typeof p === "string" ? (
          p
        ) : (
          <span key={i} className={`lp-hl lp-hl--${p.level}`}>
            {p.term}
          </span>
        ),
      )}
    </p>
  );
}

const SIDE: { persona: PersonaKey; who: string }[] = [
  { persona: "newcomer", who: "A software engineer, new to markets" },
  { persona: "trader", who: "A markets trader who follows cricket" },
];

function Solution() {
  return (
    <section className="lp-section lp-solution" aria-labelledby="lp-solution-title">
      <h2 id="lp-solution-title" className="lp-section__title">
        Gloss reads with you.
      </h2>
      <p className="lp-section__lede">
        Gloss keeps a private map of what you already know, and uses it to explain only what you're likely to miss, in
        terms you already understand.
      </p>
      <figure className="lp-side">
        <div className="lp-side__cols">
          {SIDE.map(({ persona, who }) => {
            const notes = demoNotes(persona);
            const analogy = notes.find((n) => n.analogy);
            return (
              <div key={persona} className="lp-side__col">
                <p className="lp-side__who">{who}</p>
                <p className="lp-side__count">{noteCount(notes)}</p>
                <MarkedParagraph notes={notes} />
                {analogy && (
                  <blockquote className="lp-side__quote">
                    <p>{analogy.analogy}</p>
                    <footer>
                      Gloss's note on <i>{analogy.term}</i>, in {analogy.analogyDomain} terms
                    </footer>
                  </blockquote>
                )}
              </div>
            );
          })}
        </div>
        <figcaption className="lp-side__caption">Same article. Different help.</figcaption>
      </figure>
    </section>
  );
}

/** The four steps, each shown by a clip recorded from the live app (decision 44 V4). */
const STEPS: { title: string; body: string; clip: { name: string; label: string; width: number; height: number } }[] = [
  {
    title: "Gloss learns what you know",
    body: "Every note you open or mark \u201cKnew this\u201d, and every \u201cKnow this?\u201d you answer, updates your map, right away.",
    clip: { name: "clip-know", label: "answering Know this? turns the term into a note", width: 1440, height: 900 },
  },
  {
    title: "Finds what you'd miss",
    body: "Every term and idea in the article is scored against your map. Plain maths, no AI guessing.",
    clip: { name: "clip-note", label: "tapping a highlighted term opens its note", width: 1440, height: 900 },
  },
  {
    title: "Explains it your way",
    body: "The Background uses analogies from your world, and can say it simpler. What the author is saying keeps their hedges and numbers.",
    clip: { name: "clip-simpler", label: "Say it simpler rewrites the Background one level down", width: 1440, height: 900 },
  },
  {
    title: "Your map grows",
    body: "What you learn fills in, so the notes thin out as you read more. For you then tells you which picks you're ready for.",
    clip: { name: "clip-map", label: "the knowledge map fills in three ideas", width: 1440, height: 900 },
  },
];
/** Where each loop's action happens (fractions of the frame), measured while recording. */
const FOCUS: Readonly<Record<string, Focus | undefined>> = focus.clips;

/** The map clip again, beside the final call to action (decision 46 P4; same files, 46e). */
const MAP_CLIP = { ...STEPS[3]!.clip, label: "your knowledge map filling in" };

function HowItWorks() {
  return (
    <section id="how-it-works" className="lp-section lp-how" aria-labelledby="lp-how-title">
      <h2 id="lp-how-title" className="lp-section__title">
        How it works
      </h2>
      <ol className="lp-how__steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className="lp-how__step">
            <DeviceFrame kind="laptop">
              <Clip {...s.clip} focus={FOCUS[s.clip.name]} />
            </DeviceFrame>
            <div className="lp-how__text">
              <span className="lp-how__num" aria-hidden="true">
                {i + 1}
              </span>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

const FIGURES = [
  { count: evals.adversarial, label: "deliberately broken explanations caught" },
  { count: evals.good, label: "good explanations accepted" },
  { count: evals.injection, label: "prompt-injection attempts resisted" },
] as const;

function Trust() {
  return (
    <section id="how-we-test" className="lp-section lp-trust" aria-labelledby="lp-trust-title">
      <h2 id="lp-trust-title" className="lp-section__title">
        Checked before you see it.
      </h2>
      <ul className="lp-trust__figures" aria-label="Verifier results from our evaluation">
        {FIGURES.map((f) => (
          <li key={f.label} className="lp-trust__figure">
            <span className="lp-trust__num">
              {f.count.passed}
              <span className="lp-trust__of">/{f.count.total}</span>
            </span>
            <span className="lp-trust__label">{f.label}</span>
          </li>
        ))}
      </ul>
      <dl className="lp-trust__list">
        <div className="lp-trust__item">
          <dt>Never changes the original</dt>
          <dd>
            <p>Notes sit on top of the page; the author's words stay exactly as written.</p>
          </dd>
        </div>
        <div className="lp-trust__item">
          <dt>Every explanation is verified</dt>
          <dd>
            <p>
              Each note is checked against its source paragraph before it's shown; if it doesn't pass, you get a plain
              definition instead.{" "}
              <a href={`${REPO_URL}#evaluation`} target="_blank" rel="noreferrer">
                How we test
              </a>
            </p>
          </dd>
        </div>
        <div className="lp-trust__item">
          <dt>Your reading stays yours</dt>
          <dd>
            <p>
              The AI never learns who you are or what you've read: it sees only the paragraph it explains, a reading
              level and your analogy style. Export or delete everything anytime.
            </p>
          </dd>
        </div>
      </dl>
    </section>
  );
}

function Formats() {
  return (
    <section className="lp-section lp-formats" aria-labelledby="lp-formats-title">
      <h2 id="lp-formats-title" className="lp-section__title">
        What you can read
      </h2>
      <ul className="lp-formats__list">
        {FORMATS.map((f) => (
          <li key={f.what} className="lp-formats__item">
            <span className="lp-formats__what">{f.what}</span>
            <span className="lp-formats__how lp-formats__how--notes">With notes</span>
            <span className="lp-formats__detail">{f.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
