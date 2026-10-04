import { LibraryPage } from "./pages/LibraryPage";
import { ReaderPage } from "./pages/ReaderPage";
import { matchRoute, navigate, useUrl } from "./lib/router";

export function App() {
  const url = useUrl();
  const route = matchRoute(url.pathname);
  if (route.name === "library") return <LibraryPage url={url} />;
  if (route.name === "reader") return <ReaderPage id={route.id} url={url} />;
  return (
    <main className="page">
      <p className="state">
        No page here.{" "}
        <a
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate("/");
          }}
        >
          Back to the library
        </a>
      </p>
    </main>
  );
}
