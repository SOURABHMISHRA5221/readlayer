import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";

import { App } from "./App";
import { bootsToLanding } from "./lib/boot";
import { reloadOnStaleChunk } from "./lib/staleChunk";
import "./styles/tokens.css";
import "./styles/fonts.css";
import "./styles/global.css";
import "./styles/chrome.css";
import "./styles/reader.css";
import "./styles/library.css";
import "./styles/account.css";
import "./styles/hero.css";

reloadOnStaleChunk();

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
const app = (
  <StrictMode>
    <App />
  </StrictMode>
);
// On the landing's first paint React adopts index.html's static hero (the same markup HeroStatic
// renders) instead of replacing it, so the hero text isn't painted twice: its first paint stays
// the largest contentful paint (decision 47). Every other route mounts fresh.
if (bootsToLanding()) hydrateRoot(root, app);
else createRoot(root).render(app);
