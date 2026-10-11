import { useEffect, useState } from "react";

import { Avatar } from "../components/PersonaPicker";
import { ThemeToggle } from "../components/ThemeToggle";
import { Wordmark } from "../components/Wordmark";
import { signInError, signInWithGoogle, startDemo } from "../lib/auth";
import { PERSONAS, personaParam, type PersonaKey } from "../lib/personas";
import { navigate, withParams } from "../lib/router";

type Busy = null | "google" | PersonaKey;

/**
 * The front door: your own reading (Google), or the demo — an anonymous session reading as one
 * of the sample readers, switchable later from the persona chip.
 */
export function SignInPage({ url }: { url: URL }) {
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Gloss · Sign in";
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

  const demo = async (key: PersonaKey) => {
    setBusy(key);
    setError(null);
    // Put the persona in the URL first: the app renders as soon as the session exists.
    navigate(withParams(url, { persona: personaParam(key) }), { replace: true });
    try {
      await startDemo();
    } catch (e) {
      setError(signInError(e) ?? "The demo didn't start. Try again.");
      setBusy(null);
    }
  };

  return (
    <div className="signin">
      <header className="signin__bar">
        <Wordmark size="lg" />
        <ThemeToggle />
      </header>
      <main className="signin__main">
        <section className="signin__intro" aria-labelledby="signin-title">
          <h1 id="signin-title" className="signin__title">
            Read anything. <em>Understand it your way.</em>
          </h1>
          <p className="signin__lede">
            Quiet notes on writing about any subject, only where you're likely to need them. The author's words
            stay exactly as written, and the notes thin out as you learn.
          </p>
        </section>

        <section className="signin__own" aria-labelledby="own-title">
          <h2 id="own-title" className="eyebrow">
            Your reading
          </h2>
          <button type="button" className="btn btn--primary signin__google" onClick={google} disabled={busy !== null}>
            {busy === "google" ? "Opening Google…" : "Continue with Google"}
          </button>
          <p className="signin__fine">
            We keep what the notes learn about your reading, never your email. Export or delete it any time from the
            account menu.
          </p>
        </section>

        <section className="signin__demo" aria-labelledby="demo-title">
          <h2 id="demo-title" className="eyebrow">
            Or try the demo as
          </h2>
          <ul className="signin__personas">
            {PERSONAS.map((p) => (
              <li key={p.key}>
                <button
                  type="button"
                  className="signin__persona"
                  data-persona={p.key}
                  onClick={() => demo(p.key)}
                  disabled={busy !== null}
                  aria-describedby={`persona-${p.key}`}
                >
                  <Avatar persona={p.key} initials={p.initials} />
                  <span className="signin__persona-text">
                    <span className="signin__persona-name">{busy === p.key ? "Starting…" : p.label}</span>
                    <span className="signin__persona-blurb" id={`persona-${p.key}`}>
                      {p.blurb}
                    </span>
                    <span className="signin__persona-strengths">Strong in {p.strengths.join(" · ")}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="signin__fine">No account needed. Ending the demo deletes what it recorded.</p>
        </section>

        {error && (
          <p className="signin__error" role="alert">
            {error}
          </p>
        )}
      </main>
    </div>
  );
}
