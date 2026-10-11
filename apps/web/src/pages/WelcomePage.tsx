import { useEffect, useMemo, useRef, useState } from "react";

import { profileApi } from "../lib/profileApi";
import { navigate } from "../lib/router";
import { AboutScreen, chosenDomains, EMPTY_ABOUT, frameFor, type About } from "./welcome/AboutScreen";
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
  const [about, setAbout] = useState<About>(EMPTY_ABOUT);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = "Welcome · Gloss";
    profileApi
      .profile(null)
      .then((p) => {
        const o = p.onboarding;
        setConsented(o.consented);
        setAbout((cur) => ({ ...cur, field: o.field ?? cur.field, topics: o.interests?.length ? o.interests : cur.topics }));
        setScreen(o.step === "discover" ? "discover" : "about");
      })
      .catch(() => setScreen("about"));
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
    navigate("/", { replace: true });
  };

  if (screen === "loading") return <Shell screen={1}>{null}</Shell>;
  return (
    <Shell screen={screen === "about" ? 1 : 2}>
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
