import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { initApiBase } from "./api";
import { applyAppearance, loadAppearance } from "./theme";
import "./styles/base.css";
import "./styles/palettes.css";
import "./styles.css";
import "./styles/chat.css";

// Apply the saved colour mode before the first paint so there is no flash.
applyAppearance(loadAppearance());

// The desktop app tells the page which port its backend uses; render after.
void initApiBase().finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
