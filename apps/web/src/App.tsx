import { lazy, Suspense, useEffect, useState } from "react";

import { StateView } from "./components/StateView";
import { useSession } from "./lib/auth";
import { profileApi } from "./lib/profileApi";
import { LibraryPage } from "./pages/LibraryPage";
import { ReaderPage } from "./pages/ReaderPage";
import { SignInPage } from "./pages/SignInPage";
import { matchRoute, navigate, onboardingRedirect, useUrl } from "./lib/router";

// Route chunks: the main bundle doesn't carry onboarding or the profile page (M7).
const WelcomePage = lazy(() => import("./pages/WelcomePage"));
const ProfilePage = lazy(() => import("./pages/ProfilePage"));

/** A signed-in (Google) reader goes through consent and onboarding first; demo readers never. */
function useOnboardingDone(uid: string | null, isDemo: boolean): boolean | null {
  const [done, setDone] = useState<{ uid: string; done: boolean } | null>(null);
  // Bumped when the welcome flow finishes, so the status is fetched again (not left loading).
  const [checks, setChecks] = useState(0);
  useEffect(() => {
    const again = () => setChecks((n) => n + 1);
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
    <StateView title="Opening ReadLayer…" />
  </main>
);

export function App() {
  const url = useUrl();
  const session = useSession();
  if (session.status === "loading") {
    return (
      <main className="reader__state" aria-busy="true">
        <StateView title="Opening ReadLayer…" />
      </main>
    );
  }
  if (session.status === "unavailable") {
    return (
      <main className="reader__state">
        <StateView title="Sign-in isn't set up in this build" role="alert">
          The Firebase web config is missing. Run `make web-config`, then restart the dev server.
        </StateView>
      </main>
    );
  }
  if (session.status === "signed_out") return <SignInPage url={url} />;
  return <SignedIn url={url} uid={session.uid} isDemo={session.isDemo} />;
}

function SignedIn({ url, uid, isDemo }: { url: URL; uid: string; isDemo: boolean }) {
  const route = matchRoute(url.pathname);
  const done = useOnboardingDone(uid, isDemo);
  useEffect(() => {
    const to = onboardingRedirect(done, route.name);
    if (to) navigate(to, { replace: true });
  }, [done, route.name]);
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
  if (route.name === "library") return <LibraryPage url={url} />;
  if (route.name === "reader") return <ReaderPage id={route.id} url={url} />;
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
