import { StateView } from "./components/StateView";
import { LibraryPage } from "./pages/LibraryPage";
import { ReaderPage } from "./pages/ReaderPage";
import { matchRoute, navigate, useUrl } from "./lib/router";

export function App() {
  const url = useUrl();
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
