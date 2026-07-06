import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ClientApp } from "./ClientApp";
import { ConsumerApp } from "./ConsumerApp";
import "./styles.css";

type View = "tryon" | "works" | "help" | "studio" | "test";

function currentView() {
  const params = new URLSearchParams(window.location.search);
  if (window.location.pathname === "/test" || params.get("view") === "test") return "test";
  if (window.location.pathname === "/studio" || params.get("view") === "studio") return "studio";
  if (window.location.pathname === "/works") return "works";
  if (window.location.pathname === "/help") return "help";
  return "tryon";
}

function pathForView(view: View) {
  if (view === "works") return "/works";
  if (view === "help") return "/help";
  if (view === "studio") return "/studio";
  if (view === "test") return "/test";
  return "/";
}

function Root() {
  const [view, setView] = useState<View>(currentView());

  useEffect(() => {
    const syncView = () => setView(currentView());
    window.addEventListener("popstate", syncView);
    return () => window.removeEventListener("popstate", syncView);
  }, []);

  function navigate(nextView: View) {
    window.history.pushState({}, "", pathForView(nextView));
    setView(nextView);
  }

  function openTestStudio() {
    navigate("test");
  }

  if (view === "test") {
    return (
      <>
        <button className="view-switch-button" onClick={() => navigate("studio")} type="button">
          返回内部工作台
        </button>
        <App />
      </>
    );
  }

  if (view === "studio") {
    return <ClientApp onOpenTestStudio={openTestStudio} />;
  }

  return <ConsumerApp route={view} onNavigate={navigate} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
