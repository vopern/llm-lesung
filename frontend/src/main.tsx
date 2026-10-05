import { StrictMode, useCallback, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import {
  DICTS,
  I18nContext,
  loadLang,
  saveLang,
  type Lang,
  type StringKey,
} from "./i18n";
import { Layout } from "./components/Layout";
import { ListPage } from "./pages/ListPage";
import { DetailPage } from "./pages/DetailPage";
import { AboutPage } from "./pages/AboutPage";
import { EvalPage } from "./pages/EvalPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import "./styles.css";

function App() {
  const [lang, setLangState] = useState<Lang>(() => loadLang());

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    saveLang(next);
  }, []);

  const value = useMemo(() => {
    const t = (key: StringKey) => DICTS[lang][key];
    return { lang, setLang, t };
  }, [lang, setLang]);

  return (
    <I18nContext.Provider value={value}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<ListPage />} />
            <Route path="/bill/:id" element={<DetailPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="/evaluation" element={<EvalPage />} />
            <Route path="/datenschutz" element={<PrivacyPage />} />
            <Route path="*" element={<ListPage />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </I18nContext.Provider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
