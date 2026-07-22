import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@fontsource/nunito/latin-400.css";
import "@fontsource/nunito/latin-600.css";
import "@fontsource/nunito/latin-700.css";

import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AuthProvider } from "./hooks/AuthProvider";
import "./styles.css";

// Dev-only mock backend so the UI is reviewable without a running API.
// Stripped from production builds: import.meta.env.DEV is false there.
if (import.meta.env.DEV && import.meta.env.VITE_MOCK === "1") {
  const { installMockBackend } = await import("./lib/mockBackend");
  installMockBackend();
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
);
