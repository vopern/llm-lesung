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
          Diese Seite richtet sich an technisch Interessierte. Die Berichte zeigen, wie gut die
          Analyse Mängel findet, die nachweislich in Gesetzentwürfen standen: je Testfall die
          erwartete Stelle, das Urteil und die Ausgabe des Modells, dazu die Gesamtzahlen. Die
          Testfälle stehen fest, bevor ein Lauf den Entwurf liest, und bewertet wird mechanisch —
          kein Modell bewertet sich selbst.
        </p>
      ) : (
        <p>
          This page is for technical readers. The reports show how well the analysis finds
          defects that demonstrably were in draft bills: per test case the expected passage, the
          verdict and the model&apos;s output, plus the aggregate numbers. Test cases are fixed
          before a run reads the draft, and scoring is mechanical — no model grades itself.
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
