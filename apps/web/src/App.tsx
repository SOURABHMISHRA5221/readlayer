import { StateView } from "./components/StateView";
import { useSession } from "./lib/auth";
import { LibraryPage } from "./pages/LibraryPage";
import { ReaderPage } from "./pages/ReaderPage";
import { SignInPage } from "./pages/SignInPage";
import { matchRoute, navigate, useUrl } from "./lib/router";

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
  const route = matchRoute(url.pathname);
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
