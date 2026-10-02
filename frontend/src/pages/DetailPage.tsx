import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, fetchBill, type BillDetail } from "../api";
import { useI18n } from "../i18n";
import { categoryLabel, formatDate, formatDateTime } from "../format";
import { RiskBadge } from "../components/RiskBadge";

export function DetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();

  const [bill, setBill] = useState<BillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setNotFound(false);
    setError(false);
    setBill(null);
    fetchBill(id)
      .then((b) => {
        if (alive) setBill(b);
      })
      .catch((e) => {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  if (loading) {
    return <p className="notice">{t("loading")}</p>;
  }

  if (notFound) {
    return (
      <div className="detail-message">
        <h1>{t("notFoundTitle")}</h1>
        <p>{t("notFoundBody")}</p>
        <Link className="back-link" to="/">
          ← {t("backToList")}
        </Link>
      </div>
    );
  }

  if (error || !bill) {
    return (
      <div className="detail-message">
        <p className="notice notice-error">{t("errorGeneric")}</p>
        <Link className="back-link" to="/">
          ← {t("backToList")}
        </Link>
      </div>
    );
  }

  const documents = bill.analysis_documents ?? [];
  const related = bill.related_documents ?? [];
  const analyzedIds = new Set(documents.map((d) => d.document_id));
  const docTypeLabel = (typ: string) =>
    typ === "gesetzentwurf"
      ? t("docTypeGesetzentwurf")
      : typ === "beschlussempfehlung"
        ? t("docTypeBeschlussempfehlung")
        : typ;

  return (
    <article className="detail-page">
      <Link className="back-link" to="/">
        ← {t("backToList")}
      </Link>

      <header className="detail-header">
        <div className="detail-header-top">
          <span className="doc-number">{bill.dokumentnummer}</span>
          <span className="worst-finding-label">{t("worstFinding")}</span>
          <RiskBadge level={bill.risk} />
        </div>
        <h1 className="detail-title">{bill.titel}</h1>
        <dl className="detail-meta">
          {bill.urheber && (
            <div>
              <dt>{t("initiator")}</dt>
              <dd>{bill.urheber}</dd>
            </div>
          )}
          <div>
            <dt>{t("status")}</dt>
            <dd>{bill.status ?? "–"}</dd>
          </div>
          <div>
            <dt>{t("date")}</dt>
            <dd>{formatDate(bill.datum)}</dd>
          </div>
        </dl>
        <p>
          <a
            className="pdf-link"
            href={bill.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("pdfLink")} ↗
          </a>
        </p>
        {related.length > 0 && (
          <ul className="related-documents">
            {related.map((d) => {
              const used = analyzedIds.has(d.document_id);
              return (
                <li key={d.document_id}>
                  <a
                    className={used ? "pdf-link" : "pdf-link pdf-link-unused"}
                    href={d.pdf_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={d.titel ?? undefined}
                  >
                    {docTypeLabel(d.typ)} {d.dokumentnummer} ↗
                  </a>
                  <span className="related-meta">
                    {" · "}
                    {formatDate(d.datum)}
                    {!used && <> · {t("relatedNotAnalyzed")}</>}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </header>

      {bill.summary && (
        <section className="detail-summary">
          <h2>{t("summaryHeading")}</h2>
          <p>{bill.summary}</p>
        </section>
      )}

      <section className="detail-findings">
        <h2>{t("findingsHeading")}</h2>
        {bill.findings.length === 0 ? (
          <p className="notice">{t("noFindings")}</p>
        ) : (
          <div className="finding-list">
            {bill.findings.map((f, i) => (
              <article key={i} className="finding-card">
                <div className="finding-card-head">
                  <RiskBadge level={f.severity} />
                  <span className="finding-category">
                    {categoryLabel(f.category)}
                  </span>
                </div>
                <h3 className="finding-title">{f.title}</h3>
                <p className="finding-description">{f.description}</p>
                {f.quote && <blockquote className="finding-quote">{f.quote}</blockquote>}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="method-box">
        <h2>{t("methodHeading")}</h2>
        <dl className="method-meta">
          <div>
            <dt>{t("methodPromptVersion")}</dt>
            <dd>{bill.prompt_version ?? "–"}</dd>
          </div>
          <div>
            <dt>{t("methodModel")}</dt>
            <dd>{bill.model ?? "–"}</dd>
          </div>
          <div>
            <dt>{t("methodAnalyzedAt")}</dt>
            <dd>{formatDateTime(bill.analyzed_at)}</dd>
          </div>
          <div>
            <dt>{t("methodDocuments")}</dt>
            <dd>
              {documents.length === 0 ? (
                "–"
              ) : (
                <ul className="method-documents">
                  {documents.map((d) => (
                    <li key={d.document_id}>
                      <a href={d.pdf_url} target="_blank" rel="noopener noreferrer">
                        Drs. {d.dokumentnummer}
                      </a>
                      {" · "}
                      {docTypeLabel(d.typ)}
                      {" · "}
                      {formatDate(d.datum)}
                    </li>
                  ))}
                </ul>
              )}
              {documents.some((d) => d.typ === "beschlussempfehlung") && (
                <p className="method-note">{t("methodDocumentsAmended")}</p>
              )}
            </dd>
          </div>
        </dl>
        <p className="method-disclaimer">{t("disclaimer")}</p>
      </section>
    </article>
  );
}
