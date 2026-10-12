import { useCallback, useEffect, useState } from "react";

import { TopBar } from "../components/TopBar";
import { extensionCredentials } from "../lib/auth";
import {
  connectExtension,
  disconnectExtension,
  extensionState,
  type ExtensionState,
} from "../lib/extension";
import { DEFAULT_PERSONA, personaOf, readerPersona } from "../lib/personas";
import { navigate } from "../lib/router";
import "../styles/connect.css";

/**
 * Connect the Gloss extension (M8 §D): hands this reader's session to the extension so it can
 * annotate articles anywhere. Under the onboarding gate (an unfinished reader finishes the two
 * screens first and comes back here). Demo readers connect as their sample reader.
 */

type View = ExtensionState | "checking" | "working" | "failed";

const CAN_SEE = [
  "Only the tab you click it on, and only when you click.",
  "The article's text. Never forms, comments or anything you type.",
  "Emails, phone numbers and card numbers are removed in your browser before anything is sent.",
  "It never reads mail, banking or private pages, or a page with a password or card field.",
  "A page you bring in with it is visible only to you.",
];

const INSTALL = [
  "Open chrome://extensions and turn on Developer mode (top right).",
  "Choose “Load unpacked” and pick the extension's dist folder.",
  "Pin Gloss to the toolbar, then come back here and press Check again.",
];

export default function ConnectPage({ url, isDemo }: { url: URL; isDemo: boolean }) {
  const persona = isDemo ? readerPersona(url, isDemo) ?? DEFAULT_PERSONA : null;
  const who = persona ? `the ${personaOf(persona).label} demo reader` : "you";
  const [view, setView] = useState<View>("checking");

  const check = useCallback(() => {
    setView("checking");
    void extensionState().then(setView);
  }, []);

  useEffect(() => {
    document.title = "Use Gloss on any site · Gloss";
    check();
  }, [check]);

  const connect = async () => {
    setView("working");
    const credentials = await extensionCredentials().catch(() => null);
    const ok = credentials ? await connectExtension({ ...credentials, persona }) : false;
    setView(ok ? "connected" : "failed");
  };

  const disconnect = async () => {
    setView("working");
    setView((await disconnectExtension()) ? "disconnected" : "failed");
  };

  return (
    <div className="connect">
      <TopBar url={url} />
      <main className="connect__main" id="main">
        <p className="eyebrow">The Gloss extension</p>
        <h1 className="connect__title">Notes on any article you read</h1>
        <p className="connect__lede">
          Click Gloss in your browser's toolbar on a news article and the notes you'd get here appear on that page,
          pitched to what you know. Nothing runs until you click.
        </p>

        <section className="connect__panel" aria-labelledby="connect-state" aria-busy={view === "checking" || view === "working"}>
          <h2 id="connect-state" className="connect__state" role="status">
            {view === "checking" && "Looking for the extension…"}
            {view === "working" && "One moment…"}
            {view === "missing" && "The extension isn't installed in this browser yet"}
            {view === "disconnected" && `Installed. Connect it to ${who}.`}
            {view === "connected" && `Connected to ${who}`}
            {view === "failed" && "That didn't work"}
          </h2>

          {view === "missing" && (
            <>
              <ol className="connect__steps">
                {INSTALL.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              <button type="button" className="btn btn--primary" onClick={check}>
                Check again
              </button>
            </>
          )}
          {view === "disconnected" && (
            <button type="button" className="btn btn--primary" onClick={() => void connect()}>
              Connect
            </button>
          )}
          {view === "connected" && (
            <>
              <p className="connect__note">Open any news article and click Gloss in your toolbar.</p>
              <div className="connect__actions">
                <button type="button" className="btn btn--primary" onClick={() => void connect()}>
                  Connect again
                </button>
                <button type="button" className="btn btn--quiet" onClick={() => void disconnect()}>
                  Disconnect
                </button>
              </div>
            </>
          )}
          {view === "failed" && (
            <>
              <p className="connect__note">
                Reload the extension in chrome://extensions, then try again. Your notes here are unaffected.
              </p>
              <button type="button" className="btn btn--primary" onClick={check}>
                Try again
              </button>
            </>
          )}
        </section>

        <section className="connect__group" aria-labelledby="connect-see">
          <h2 id="connect-see">What it can see</h2>
          <ul>
            {CAN_SEE.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <p className="connect__more">
            <a
              href="/privacy"
              onClick={(e) => {
                e.preventDefault();
                navigate("/privacy");
              }}
            >
              What Gloss stores
            </a>
          </p>
        </section>
      </main>
    </div>
  );
}
