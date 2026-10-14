import { Wordmark } from "../components/Wordmark";
import { navigate } from "../lib/router";
import { EXTENSION_RELEASE_URL, REPO_URL } from "./links";

export function Footer() {
  return (
    <footer className="lp-footer">
      <Wordmark />
      <p className="lp-footer__built">Built on Gemini and Google Cloud</p>
      <p className="lp-footer__built">Illustrations made with Google's image model.</p>
      <nav className="lp-footer__links" aria-label="About Gloss">
        <a href="#how-it-works">How it works</a>
        <a href={EXTENSION_RELEASE_URL} target="_blank" rel="noreferrer">
          Get the extension
        </a>
        <a href={REPO_URL} target="_blank" rel="noreferrer">
          GitHub
        </a>
        <a
          href="/privacy"
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            navigate("/privacy");
          }}
        >
          Privacy
        </a>
      </nav>
    </footer>
  );
}
