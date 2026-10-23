import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchHighlights, type Highlight } from "../api";
import { useI18n } from "../i18n";
import { categoryLabel, formatDate } from "../format";
import { RiskBadge } from "../components/RiskBadge";

function HighlightCard({ highlight: h }: { highlight: Highlight }) {
  const { t } = useI18n();
  const f = h.finding;
  return (
    <article className="highlight-card">
      <h2>{h.headline}</h2>
      <p className="highlight-bill">
        Drs. {h.dokumentnummer} · {h.titel}
        {h.added && <> · {formatDate(h.added)}</>}
      </p>
      {h.why && <p>{h.why}</p>}
      <div className="finding-card">
        <div className="finding-card-head">
          {f.severity && <RiskBadge level={f.severity} />}
          {f.category && <span className="finding-category">{categoryLabel(f.category)}</span>}
          {f.analyzed_at && (
            <span className="related-meta">
              {t("highlightsAnalyzedAt")} {formatDate(f.analyzed_at)}
            </span>
          )}
        </div>
        <h3 className="finding-title">{f.title}</h3>
        {f.quote && <blockquote className="finding-quote">{f.quote}</blockquote>}
      </div>
      {h.finding_id !== null ? (
        <Link to={`/bill/${h.bill_id}#finding-${h.finding_id}`}>{t("highlightsToFinding")} →</Link>
      ) : (
        <p className="notice">{t("highlightsFindingGone")}</p>
      )}
      {h.media.length > 0 && (
        <>
          <h3>{t("highlightsMedia")}</h3>
          <ul className="highlight-media">
            {h.media.map((m) => (
              <li key={m.url}>
                <a href={m.url} target="_blank" rel="noopener noreferrer">
                  {m.title ?? m.outlet ?? m.url} ↗
                </a>
                {(m.outlet && m.title) || m.date ? (
                  <span className="related-meta">
                    {" · "}
                    {[m.title ? m.outlet : null, m.date && formatDate(m.date)]
                      .filter(Boolean)
                      .join(", ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}

export function HighlightsPage() {
  const { t } = useI18n();
  const [highlights, setHighlights] = useState<Highlight[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchHighlights()
      .then((h) => alive && setHighlights(h))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <article className="highlights-page prose">
      <h1>{t("highlightsTitle")}</h1>
      <p>{t("highlightsIntro")}</p>
      <p className="method-disclaimer">{t("disclaimer")}</p>
      {error ? (
        <p className="notice notice-error">{t("errorGeneric")}</p>
      ) : !highlights ? (
        <p className="notice">{t("loading")}</p>
      ) : highlights.length === 0 ? (
        <p className="notice">{t("highlightsEmpty")}</p>
      ) : (
        <div className="highlight-list">
          {highlights.map((h, i) => (
            <HighlightCard key={`${h.bill_id}-${i}`} highlight={h} />
          ))}
        </div>
      )}
    </article>
  );
}
