import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { useState } from "react";
import { App } from "./App";
import { ClientApp } from "./ClientApp";
import "./styles.css";

function Root() {
  const initialView = new URLSearchParams(window.location.search).get("view") === "test" ? "test" : "client";
  const [view, setView] = useState<"client" | "test">(initialView);

  function openClient() {
    window.history.replaceState({}, "", window.location.pathname);
    setView("client");
  }

  function openTestStudio() {
    window.history.replaceState({}, "", `${window.location.pathname}?view=test`);
    setView("test");
  }

  if (view === "test") {
    return (
      <>
        <button className="view-switch-button" onClick={openClient} type="button">
          正式前端
        </button>
        <App />
      </>
    );
  }

  return <ClientApp onOpenTestStudio={openTestStudio} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
