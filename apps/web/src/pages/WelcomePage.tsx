import { useEffect, useMemo, useRef, useState } from "react";

import { countryFromLocale } from "../lib/country";
import { markFeedStale } from "../lib/feedStale";
import { profileApi } from "../lib/profileApi";
import { navigate } from "../lib/router";
import {
  AboutScreen,
  chosenDomains,
  CONSENT_VERSION,
  EMPTY_ABOUT,
  frameFor,
  MAX_TOPICS,
  type About,
} from "./welcome/AboutScreen";
import { DiscoverScreen } from "./welcome/DiscoverScreen";
import { Shell } from "./welcome/parts";
import "../styles/welcome.css";

export { CONSENT_VERSION } from "./welcome/AboutScreen";

/**
 * Onboarding in 2 screens for a signed-in reader (decision 41; DESIGN §4, §11.4): "Tell Margo
 * about you" (field, topics, optional free text, inline consent), then "Here's what's out there
 * for you" (live results to pick from, one Know this? each, Margo's readback). Resumes on
 * screen 2 after a reload; Edit goes back to screen 1 with the choices kept.
 */
export default function WelcomePage() {
  const [screen, setScreen] = useState<"loading" | "about" | "discover">("loading");
  const [consented, setConsented] = useState(false);
  const [redo, setRedo] = useState(false);
  const [about, setAbout] = useState<About>(EMPTY_ABOUT);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = "Welcome · Gloss";
    profileApi
      .profile(null)
      .then((p) => {
        const o = p.onboarding;
        if (o.done && !o.redo) {
          // Finished readers come back here only through Redo setup (decision 48): saving screen
          // 1 outside a redo would mark them not onboarded and gate the app.
          navigate("/", { replace: true });
          return;
        }
        setRedo(!!o.redo);
        // A reader who agreed to an older consent text sees the current one once.
        setConsented(o.consented && o.consent_version === CONSENT_VERSION);
        setAbout((cur) => ({
          ...cur,
          field: o.field ?? cur.field,
          topics: o.interests?.length ? o.interests.slice(0, MAX_TOPICS) : cur.topics,
          // A saved country wins; otherwise the browser's locale suggests one (decision 50).
          country: p.settings.country ?? cur.country ?? countryFromLocale(navigator.language),
        }));
        setScreen(o.step === "discover" || o.redo === "discover" ? "discover" : "about");
      })
      .catch(() => {
        setAbout((cur) => ({ ...cur, country: cur.country ?? countryFromLocale(navigator.language) }));
        setScreen("about");
      });
  }, []);

  // Each screen change moves focus to its heading, so keyboard and screen-reader users start there.
  useEffect(() => {
    if (screen !== "loading") heading.current?.focus();
  }, [screen]);

  // Concepts are searched for directly, so their domains aren't added as topics here.
  const topics = useMemo(
    () => chosenDomains({ ...EMPTY_ABOUT, topics: about.topics, mapped: about.mapped }),
    [about.topics, about.mapped],
  );
  const concepts = useMemo(() => about.concepts.map((c) => c.id), [about.concepts]);
  const frame = frameFor(about.field)[0] ?? null;

  const finish = () => {
    window.dispatchEvent(new Event("rl:onboarding-changed"));
    markFeedStale();
    navigate("/", { replace: true });
  };

  const cancel = redo
    ? async () => {
        await profileApi.cancelRedo().catch(() => undefined);
        navigate("/profile");
      }
    : undefined;

  if (screen === "loading") return <Shell screen={1}>{null}</Shell>;
  return (
    <Shell screen={screen === "about" ? 1 : 2} onCancel={cancel}>
      {screen === "about" ? (
        <AboutScreen
          heading={heading}
          about={about}
          onChange={setAbout}
          consented={consented}
          onConsented={() => setConsented(true)}
          onSaved={() => setScreen("discover")}
        />
      ) : (
        <DiscoverScreen
          heading={heading}
          topics={topics}
          concepts={concepts}
          frame={frame}
          onEdit={() => setScreen("about")}
          onFinish={finish}
        />
      )}
    </Shell>
  );
}
