import { lazy, Suspense, useEffect, useState } from "react";

import { StateView } from "./components/StateView";
import { HeroStatic } from "./landing/Hero";
import { useSession } from "./lib/auth";
import { bootsToLanding } from "./lib/boot";
import { profileApi } from "./lib/profileApi";
import { LibraryPage } from "./pages/LibraryPage";
import {
  matchRoute,
  navigate,
  onboardingRedirect,
  rememberReturn,
  returnsAfterOnboarding,
  takeReturn,
  useUrl,
} from "./lib/router";

// Route chunks: the main bundle doesn't carry onboarding or the profile page (M7), the reader
// (decision 67), nor the landing and privacy pages (only HeroStatic, the landing's first paint, is in it).
const WelcomePage = lazy(() => import("./pages/WelcomePage"));
const ProfilePage = lazy(() => import("./pages/ProfilePage"));
const LandingPage = lazy(() => import("./pages/LandingPage"));
const PrivacyPage = lazy(() => import("./pages/PrivacyPage"));
const ConnectPage = lazy(() => import("./pages/ConnectPage"));
// The reader and its annotator (decision 67): the landing never needs them, and the main bundle
// stays inside its budget.
const loadReader = () => import("./pages/ReaderPage");
const ReaderPage = lazy(() => loadReader().then((m) => ({ default: m.ReaderPage })));

/** Fetch the reader chunk while the library is idle, so the first article opens at once. */
function useReaderPreload(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 1500));
    idle(() => void loadReader().catch(() => undefined));
  }, [active]);
}

/** A signed-in (Google) reader goes through consent and onboarding first; demo readers never. */
function useOnboardingDone(uid: string | null, isDemo: boolean): boolean | null {
  const [done, setDone] = useState<{ uid: string; done: boolean } | null>(null);
  // Bumped when the welcome flow finishes, so the status is fetched again (not left loading).
  const [checks, setChecks] = useState(0);
  useEffect(() => {
    // Forget the old answer at once: with a stale "not done", navigating home right after the
    // flow finishes would bounce the reader back to /welcome before the re-check lands.
    const again = () => {
      setDone(null);
      setChecks((n) => n + 1);
    };
    window.addEventListener("rl:onboarding-changed", again);
    return () => window.removeEventListener("rl:onboarding-changed", again);
  }, []);
  useEffect(() => {
    if (!uid || isDemo) return;
    let live = true;
    profileApi
      .profile(null)
      .then((p) => live && setDone({ uid, done: p.onboarding.done }))
      .catch(() => live && setDone({ uid, done: true })); // never lock a reader out on an error
    return () => {
      live = false;
    };
  }, [uid, isDemo, checks]);
  if (isDemo) return true;
  return done && done.uid === uid ? done.done : null;
}

const loading = (
  <main className="reader__state" aria-busy="true">
    <StateView title="Opening Gloss…" />
  </main>
);

export function App() {
  const url = useUrl();
  const session = useSession();
  // Public for everyone, signed in or not, and never gated by onboarding.
  if (matchRoute(url.pathname).name === "privacy") {
    return (
      <Suspense fallback={null}>
        <PrivacyPage />
      </Suspense>
    );
  }
  // Keep painting what index.html painted: the static hero, or the neutral shell.
  if (session.status === "loading") return bootsToLanding() ? <HeroStatic /> : loading;
  if (session.status === "unavailable") {
    return (
      <main className="reader__state">
        <StateView title="Sign-in isn't set up in this build" role="alert">
          The Firebase web config is missing. Run `make web-config`, then restart the dev server.
        </StateView>
      </main>
    );
  }
  if (session.status === "signed_out") {
    return (
      <Suspense fallback={<HeroStatic />}>
        <LandingPage url={url} />
      </Suspense>
    );
  }
  return <SignedIn url={url} uid={session.uid} isDemo={session.isDemo} />;
}

function SignedIn({ url, uid, isDemo }: { url: URL; uid: string; isDemo: boolean }) {
  const route = matchRoute(url.pathname);
  const done = useOnboardingDone(uid, isDemo);
  useReaderPreload(done === true && (route.name === "library" || route.name === "feed"));
  useEffect(() => {
    const to = onboardingRedirect(done, route.name);
    if (!to) return;
    if (returnsAfterOnboarding(route.name)) rememberReturn(window.location.pathname);
    navigate(to, { replace: true });
  }, [done, route.name]);
  // A signed-out deep link opens once the reader is in (and through onboarding, if new).
  useEffect(() => {
    if (done !== true) return;
    const back = takeReturn();
    if (back && back !== window.location.pathname) navigate(back + window.location.search, { replace: true });
  }, [done]);
  if (done === null || (done === false && route.name !== "welcome")) return loading;
  if (route.name === "welcome")
    return (
      <Suspense fallback={loading}>
        <WelcomePage />
      </Suspense>
    );
  if (route.name === "profile")
    return (
      <Suspense fallback={loading}>
        <ProfilePage url={url} />
      </Suspense>
    );
  if (route.name === "connect")
    return (
      <Suspense fallback={loading}>
        <ConnectPage url={url} isDemo={isDemo} />
      </Suspense>
    );
  if (route.name === "library" || route.name === "feed") return <LibraryPage url={url} />;
  if (route.name === "reader")
    return (
      <Suspense fallback={loading}>
        <ReaderPage id={route.id} url={url} />
      </Suspense>
    );
  return (
    <main className="reader__state">
      <StateView
        title="There's no page here"
        actions={
          <a
            className="btn btn--primary"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
          >
            Go to the library
          </a>
        }
      >
        The link may be mistyped. Everything we have is in the library.
      </StateView>
    </main>
  );
}
