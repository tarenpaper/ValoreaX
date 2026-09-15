import React from "react";
import ReactDOM from "react-dom/client";
import { Analytics } from "@vercel/analytics/react";
import App from "./App";
import AuthGate from "./auth/AuthGate";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthGate>{session => <App session={session} />}</AuthGate>
    <Analytics />
  </React.StrictMode>,
);
