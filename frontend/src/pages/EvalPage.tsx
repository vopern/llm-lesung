import { useEffect, useState } from "react";
import { evalReportUrl, fetchEvalReports, type EvalReport } from "../api";
import { useI18n } from "../i18n";
import { formatDateTime } from "../format";

export function EvalPage() {
  const { t, lang } = useI18n();
  const [reports, setReports] = useState<EvalReport[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchEvalReports()
      .then((r) => alive && setReports(r))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <article className="eval-page prose">
      <h1>{t("evalTitle")}</h1>
      {lang === "de" ? (
        <p>
          Diese Seite richtet sich an technisch Interessierte. Die Evaluierungen sollen messen, wie gut die
          Analyse bekannte Mängel in früheren Gesetzentwürfen findet und bestehen aus verschiedenen Testfällen:
          jeder Testfall definiert eine Passage, eine Kategorie und den passenden Befund in einem Entwurf.
          Jede Evaluierung enthält die Ergebnisse der Analyse der Entwürfe und aggregierte Metriken.
          Testfälle werden mechanisch ausschließlich über die gefundene Passage bewertet.
        </p>
      ) : (
        <p>
          This page is for technical readers. The evaluations are meant to measure how well the
          analysis finds known defects in earlier draft bills, and consist of individual test cases:
          each test case defines a passage, a category and the matching finding in a draft. Each
          evaluation contains the results of analysing the drafts and aggregate metrics. Test cases
          are scored mechanically, solely by the passage found.
        </p>
      )}
      <p className="method-disclaimer">{t("disclaimer")}</p>

      <h2>{t("evalReports")}</h2>
      {error ? (
        <p className="notice notice-error">{t("errorGeneric")}</p>
      ) : !reports ? (
        <p className="notice">{t("loading")}</p>
      ) : reports.length === 0 ? (
        <p className="notice">{t("evalNoReports")}</p>
      ) : (
        <ul className="eval-reports">
          {reports.map((r) => (
            <li key={r.path}>
              <a href={evalReportUrl(r.path)} target="_blank" rel="noopener noreferrer">
                {r.title} ↗
              </a>
              <span className="related-meta">
                {" · "}
                {formatDateTime(r.modified)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
