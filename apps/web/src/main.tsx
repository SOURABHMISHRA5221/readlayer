import { ANNOTATOR_VERSION } from "@readlayer/annotator";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Placeholder until M6 builds the reader; proves the workspace wiring and the Hosting deploy.
function App() {
  return (
    <main style={{ maxWidth: "36rem", margin: "4rem auto", padding: "0 1rem", font: "18px/1.6 Georgia, serif" }}>
      <h1>ReadLayer</h1>
      <p>A personal reading layer. Coming soon.</p>
      <p style={{ opacity: 0.6, fontSize: "0.8rem" }}>annotator {ANNOTATOR_VERSION}</p>
    </main>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
