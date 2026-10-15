import { useEffect } from "react";

import { Margo, type MargoMood } from "../../components/Margo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Wordmark } from "../../components/Wordmark";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import type { PersonaKey } from "../../lib/personas";
import { Clip, type Focus } from "../Clip";
import focus from "../clipFocus.json";
import { demoNotes, noteCount, type DemoNote } from "../demoData";
import { paragraph } from "../demoParagraph.json";
import { DESKTOP_PAIR_QUERY, DeviceFrame, Still } from "../DeviceFrame";
import { Footer } from "../Footer";
import { MargoHero } from "../MargoHero";
import { ProblemArt } from "../ProblemArt";
import { ReshapeDemo } from "./ReshapeDemo";
import "../landing.css";
import "./v2.css";

/**
 * /v2: a view-only concept of the landing from a teammate's prompt (docs/plans/landing-v2.md,
 * decision 63), for discussion. Same layout and classes as the landing at /, the prompt's copy,
 * and the reshape demo. Linked from nowhere, noindex while mounted, and every button does nothing:
 * nothing here signs in, starts a demo, calls the API or navigates into the app. Removed before
 * submission.
 */

const TITLE = "Gloss · Same content. Your shape.";
const PLACEHOLDER = "[X/Y]";

/** noindex while /v2 is mounted; the landing at / is left as it was. */
function useConceptHead() {
  useEffect(() => {
    const before = document.title;
    document.title = TITLE;
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.append(meta);
    return () => {
      meta.remove();
      document.title = before;
    };
  }, []);
}

const VALUES: { mood: MargoMood; lead: string; rest: string }[] = [
  { mood: "think", lead: "Pick your length.", rest: "Shorter for a quick read, full for depth. Same source either way." },
  { mood: "happy", lead: "Pick your level.", rest: "Simpler or more technical, built from the same sentences." },
  { mood: "idle", lead: "Pick your format.", rest: "Read, listen, watch, or scan. Every version comes from the same source." },
];

const WORKS_ON = ["Articles", "Papers", "Lectures", "Videos", "Podcasts", "Documentaries", "Any link", "Chrome extension"];

function Proof({ where }: { where: "wide" | "narrow" }) {
  return (
    <p className={`lp-proof lp-proof--${where}`}>
      <a href="#how-we-test">
        Every reshaped sentence is checked against the original. {PLACEHOLDER} reshaped passages traced correctly in our
        tests.
      </a>
    </p>
  );
}

/** Inert calls to action: they look like the landing's and do nothing. */
function Ctas() {
  return (
    <div className="lp-ctas">
      <div className="lp-ctas__row">
        <button type="button" className="btn btn--primary lp-cta">
          Reshape an article
        </button>
        <button type="button" className="btn lp-cta">
          Sign in with Google
        </button>
      </div>
      <p className="lp-ctas__fine">The demo needs no account, and ending it deletes what it recorded.</p>
    </div>
  );
}

export default function LandingV2() {
  useConceptHead();
  return (
    <div className="lp lp2">
      <header className="lp-bar">
        <Wordmark size="lg" />
        <nav className="lp-nav" aria-label="Main">
          <a className="lp-nav__link lp-nav__link--wide" href="#how-it-works">
            How it works
          </a>
          <a className="lp-nav__link lp-nav__link--wide" href="/privacy">
            Privacy
          </a>
          <button type="button" className="lp-nav__link">
            Sign in
          </button>
          <button type="button" className="btn btn--primary lp-nav__cta">
            Reshape something
          </button>
          <div className="lp-bar__end">
            <ThemeToggle />
          </div>
        </nav>
      </header>
      <main className="lp-main">
        <section className="lp-hero" aria-labelledby="lp-hero-title">
          <div className="lp-hero__copy">
            <h1 id="lp-hero-title" className="lp-hero__title">
              Same content. <span className="lp-hero__mark">Your shape.</span>
            </h1>
            <p className="lp-hero__sub">
              Every article, video, podcast, and paper comes in one fixed shape. Reshape it for how you're reading right
              now. Every sentence traces back to the original.
            </p>
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
            <Proof where="wide" />
            <Ctas />
            <div className="lp-readwith">
              <span className="lp-readwith__label">Works on:</span>
              <ul className="lp-readwith__chips">
                {WORKS_ON.map((c) => (
                  <li key={c} className="lp-chip">
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <ReshapeDemo />
          <Proof where="narrow" />
        </section>
        <SeeIt />
        <InBrowser />
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
              Your next piece, in your shape.
            </h2>
            <Ctas />
          </div>
          <figure className="lp-final__map">
            <DeviceFrame kind="laptop">
              <Clip {...MAP_CLIP} focus={FOCUS[MAP_CLIP.name]} />
            </DeviceFrame>
            <figcaption>Your map of what you know fills in as you read.</figcaption>
          </figure>
        </section>
      </main>
      <Footer />
    </div>
  );
}

function SeeIt() {
  const wide = useMediaQuery(DESKTOP_PAIR_QUERY);
  return (
    <section className="lp-section lp-action" aria-labelledby="lp-action-title">
      <h2 id="lp-action-title" className="lp-section__title">
        See it in action
      </h2>
      <figure className="lp-action__figure">
        {wide ? (
          <div className="lp-action__pair">
            <DeviceFrame kind="monitor">
              <Still
                name="shot-feed"
                width={1440}
                height={900}
                alt="The Gloss For you feed on a monitor, picked for a software engineer learning economics: a six-minute video marked Ready for you with Open in Gloss, and one marked A stretch: read up on Income distribution first."
              />
            </DeviceFrame>
            <DeviceFrame kind="laptop">
              <Still
                name="shot-reader"
                width={1440}
                height={900}
                alt="The Gloss reader on a laptop: an Economic Times paragraph about a 25 bps rate hike, with the note on Basis points open in the margin, its Background using a software analogy."
              />
            </DeviceFrame>
          </div>
        ) : (
          <DeviceFrame kind="phone">
            <Still
              name="shot-phone"
              width={390}
              height={844}
              alt="The Gloss reader on a phone: the note on Basis points as a sheet that slides up from the bottom of the article."
            />
          </DeviceFrame>
        )}
        <figcaption className="lp-action__caption">
          Same Economic Times article, three shapes: full read, 2-minute version, and audio. Each line links back to the
          original.
        </figcaption>
      </figure>
    </section>
  );
}

function InBrowser() {
  return (
    <section className="lp-section lp-split lp-split--flip lp-ext" aria-labelledby="lp-ext-title">
      <div className="lp-split__copy">
        <h2 id="lp-ext-title" className="lp-section__title">
          Reshape in your browser.
        </h2>
        <p className="lp-section__lede">Open any page and pick a shape.</p>
        <ul className="lp-ext__claims">
          <li>It has no access to any site until you click it, and then only to that tab.</li>
          <li>It never reads mail, banking, sign-in or private pages, or a page with a password or card field.</li>
          <li>Emails, phone, card, Aadhaar and PAN numbers are removed on your device before the text is sent.</li>
        </ul>
        <h3 className="lp-ext__steps-title">Install it in four steps</h3>
        <ol className="lp-ext__steps">
          <li>
            Download <code>gloss-extension.zip</code> from the release and unzip it.
          </li>
          <li>
            In <code>chrome://extensions</code>, turn on Developer mode, choose Load unpacked and pick the folder; then pin
            Gloss from the puzzle-piece menu.
          </li>
          <li>In Gloss, open your account menu, choose Use Gloss on any site, then Connect (a demo session works).</li>
          <li>Open a news article, click Gloss in the toolbar, then Read this page.</li>
        </ol>
        <span className="btn btn--primary lp-ext__get">Get the extension (v0.8.2)</span>
      </div>
      <figure className="lp-split__figure lp-ext__figure">
        <DeviceFrame kind="laptop">
          <Still
            name="shot-extension"
            width={1440}
            height={900}
            alt="Wikipedia's Yield curve article in Chrome with the Gloss extension: terms a newcomer would miss are underlined, and the note on Term structure of interest rates is open, its Background using a software analogy."
          />
        </DeviceFrame>
        <div className="lp-ext__popup">
          <Still
            name="shot-popup"
            width={300}
            height={188}
            alt="The Gloss extension's popup for a demo newcomer: a Read this page button, and the line Nothing runs until you press this."
          />
        </div>
      </figure>
    </section>
  );
}

function WatchAndListen() {
  return (
    <section className="lp-section lp-split lp-watch" aria-labelledby="lp-watch-title">
      <div className="lp-split__copy">
        <h2 id="lp-watch-title" className="lp-section__title">
          Videos and podcasts, your shape.
        </h2>
        <p className="lp-section__lede">
          Paste a YouTube video or podcast link. Get the transcript reshaped by length or level, with each line pointing
          to the moment it came from. Tap any line to play that moment.
        </p>
        <p className="lp-watch__fine">
          The transcript is made automatically and can contain errors; the recording is always the source.
        </p>
      </div>
      <figure className="lp-split__figure">
        <DeviceFrame kind="laptop">
          <Still
            name="shot-media"
            width={1440}
            height={900}
            alt="A short Fireship video open in Gloss: the player, the transcript with a time button on each paragraph, and the note on Decompiler open beside the highlighted word decompile."
          />
        </DeviceFrame>
      </figure>
    </section>
  );
}

function Problem() {
  return (
    <section className="lp-section lp-problem" aria-labelledby="lp-problem-title">
      <header className="lp-problem__head">
        <h2 id="lp-problem-title" className="lp-section__title">
          One shape doesn't fit every reader.
        </h2>
        <p className="lp-problem__intro">Three ways a good article loses its reader.</p>
      </header>
      <ol className="lp-problem__list">
        <li className="lp-problem__item">
          <ProblemArt
            name="jargon"
            alt="Margo, a page with a worried face, holds an article with three words highlighted in teal and a question mark above."
          />
          <h3>Too long for this moment</h3>
        </li>
        <li className="lp-problem__item">
          <ProblemArt name="tabs" alt="A dozen browser tabs burst out of a laptop screen while Margo looks on, alarmed." />
          <h3>Too dense for this reader</h3>
        </li>
        <li className="lp-problem__item">
          <ProblemArt
            name="shredder"
            alt="A full article page goes into a shredder and only a three-line strip comes out; Margo watches, worried."
          />
          <h3>Wrong format for this place</h3>
        </li>
      </ol>
      <p className="lp-problem__close">Same content. No two readers need it in the same shape.</p>
    </section>
  );
}

/** The current landing's side-by-side, unchanged apart from the heading and lede. */
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
        It learns your shapes.
      </h2>
      <p className="lp-section__lede">
        The app remembers the lengths, levels, and formats you pick, so next time it starts where you like it.
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

/** Same clips as the landing; titles from the prompt, bodies taken word for word from it. */
const STEPS: { title: string; body: string; clip: { name: string; label: string; width: number; height: number } }[] = [
  {
    title: "Pick a shape",
    body: "Read, listen, watch, or scan.",
    clip: { name: "clip-know", label: "answering Know this? turns the term into a note", width: 1440, height: 900 },
  },
  {
    title: "Reshape it, sentence by sentence",
    body: "Every sentence traces back to the original.",
    clip: { name: "clip-note", label: "tapping a highlighted term opens its note", width: 1440, height: 900 },
  },
  {
    title: "Check each line against the source",
    body: "Every reshaped sentence is checked against the original.",
    clip: { name: "clip-simpler", label: "Say it simpler rewrites the Background one level down", width: 1440, height: 900 },
  },
  {
    title: "Save the shapes you like",
    body: "The app remembers the lengths, levels, and formats you pick, so next time it starts where you like it.",
    clip: { name: "clip-map", label: "the knowledge map fills in three ideas", width: 1440, height: 900 },
  },
];
const FOCUS: Readonly<Record<string, Focus | undefined>> = focus.clips;
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
  "reshaped lines traced to source",
  "changed-meaning lines caught",
  "shapes kept the original's facts",
];

function Trust() {
  return (
    <section id="how-we-test" className="lp-section lp-trust" aria-labelledby="lp-trust-title">
      <h2 id="lp-trust-title" className="lp-section__title">
        Checked before you see it.
      </h2>
      <ul className="lp-trust__figures" aria-label="Test results (placeholders)">
        {FIGURES.map((label) => (
          <li key={label} className="lp-trust__figure">
            <span className="lp-trust__num">{PLACEHOLDER}</span>
            <span className="lp-trust__label">{label}</span>
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
              definition instead. <span className="lp2-inert-link">How we test</span>
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

const READ_LIST = ["Articles", "Papers", "Lectures", "Videos", "Podcasts", "Documentaries"];

function Formats() {
  return (
    <section className="lp-section lp-formats" aria-labelledby="lp-formats-title">
      <h2 id="lp-formats-title" className="lp-section__title">
        What you can read
      </h2>
      <ul className="lp-formats__list">
        {READ_LIST.map((what) => (
          <li key={what} className="lp-formats__item">
            <span className="lp-formats__what">{what}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
