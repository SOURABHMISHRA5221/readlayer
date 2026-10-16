import { DeviceFrame, Still } from "./DeviceFrame";
import { EXTENSION_RELEASE_URL } from "./links";

/** The production extension's popup at 1x (`tools/shots/landing_extension.py`). */
const POPUP = { width: 300, height: 188 };

/**
 * "Gloss in your browser" (decision 61 B): the Chrome extension on a real page, what it can and
 * can't see (README's words, checked against `extension/src/redact.ts` and `refuse.ts`), and the
 * README's install steps for the pinned 0.8.2 release. No Web Store or other-browser claim.
 */
export function GlossInBrowser() {
  return (
    <section className="lp-section lp-split lp-split--flip lp-ext" aria-labelledby="lp-ext-title">
      <div className="lp-split__copy">
        <h2 id="lp-ext-title" className="lp-section__title">
          Gloss in your browser
        </h2>
        <p className="lp-section__lede">
          Following the news somewhere else? The Gloss extension for Chrome puts the same notes on the page you're on.
        </p>
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
            In <code>chrome://extensions</code>, turn on Developer mode, choose Load unpacked and pick the folder; then pin Gloss from the puzzle-piece menu.
          </li>
          <li>In Gloss, open your account menu, choose Use Gloss on any site, then Connect (a demo session works).</li>
          <li>Open a news article, click Gloss in the toolbar, then Read this page.</li>
        </ol>
        <a className="btn btn--primary lp-ext__get" href={EXTENSION_RELEASE_URL} target="_blank" rel="noreferrer">
          Get the extension (v0.8.2)
        </a>
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
            {...POPUP}
            alt="The Gloss extension's popup for a demo newcomer: a Read this page button, and the line Nothing runs until you press this."
          />
        </div>
      </figure>
    </section>
  );
}
