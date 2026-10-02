import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";
import { useI18n } from "../i18n";

function LangToggle() {
  const { lang, setLang } = useI18n();
  return (
    <div className="lang-toggle" role="group" aria-label="Language">
      <button
        type="button"
        className={lang === "de" ? "active" : ""}
        aria-pressed={lang === "de"}
        onClick={() => setLang("de")}
      >
        DE
      </button>
      <button
        type="button"
        className={lang === "en" ? "active" : ""}
        aria-pressed={lang === "en"}
        onClick={() => setLang("en")}
      >
        EN
      </button>
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="app">
      <header className="site-header">
        <div className="container header-inner">
          <div className="brand">
            <NavLink to="/" className="brand-title">
              LLM-Lesung
            </NavLink>
            <p className="brand-subtitle">{t("subtitle")}</p>
          </div>
          <nav className="site-nav">
            <NavLink to="/" end className="nav-link">
              {t("navBills")}
            </NavLink>
            <NavLink to="/about" className="nav-link">
              {t("navAbout")}
            </NavLink>
            <LangToggle />
          </nav>
        </div>
      </header>
      <main className="container main-content">{children}</main>
      <footer className="site-footer">
        <div className="container">
          {t("footer")} ·{" "}
          <NavLink to="/evaluation" className="footer-link">
            {t("evalLink")}
          </NavLink>
        </div>
      </footer>
    </div>
  );
}
