import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/tokens.css";
import "./styles/fonts.css";
import "./styles/global.css";
import "./styles/chrome.css";
import "./styles/reader.css";
import "./styles/library.css";
import "./styles/account.css";
import "./styles/hero.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
