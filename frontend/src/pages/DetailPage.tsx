import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  ApiError,
  fetchBill,
  type AnalysisDocument,
  type BillDetail,
  type Exploit,
  type Finding,
  type QuoteLocation,
} from "../api";
import { useI18n } from "../i18n";
import {
  CONSTITUTIONAL_CATEGORIES,
  RISK_LABELS,
  categoryLabel,
  formatDate,
  formatDateTime,
  musterLabel,
} from "../format";
import { Feedback } from "../components/Feedback";
import { RiskBadge } from "../components/RiskBadge";

// Where a finding's quote stands: a link to that page of the PDF and the
// passage around it, so the quote can be checked without searching.
function QuoteSource({
  location,
  documents,
}: {
  location: QuoteLocation;
  documents: AnalysisDocument[];
}) {
  const { t } = useI18n();
  const doc = documents.find((d) => d.document_id === location.document_id);
  return (
    <div className="quote-source">
      {doc && (
        <a
          className="quote-page-link"
          href={`${doc.pdf_url}#page=${location.page}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          Drs. {doc.dokumentnummer}, {t("quotePage")} {location.page} ↗
        </a>
      )}
      <details className="quote-context">
        <summary>{t("quoteContext")}</summary>
        <p>
          {location.before}
          <mark>{location.match}</mark>
          {location.after}
        </p>
      </details>
    </div>
  );
}

function FindingCard({
  finding: f,
  documents,
}: {
  finding: Finding;
  documents: AnalysisDocument[];
}) {
  return (
    <article className="finding-card">
      <div className="finding-card-head">
        <RiskBadge level={f.severity} />
        <span className="finding-category">{categoryLabel(f.category)}</span>
      </div>
      <h3 className="finding-title">{f.title}</h3>
      <p className="finding-description">{f.description}</p>
      {f.quote && <blockquote className="finding-quote">{f.quote}</blockquote>}
      {f.location && <QuoteSource location={f.location} documents={documents} />}
      <Feedback kind="finding" id={f.id} />
    </article>
  );
}

// An attack from the adversarial pass. Its severity is plain text, not a
// badge: it never enters the bill's severity.
function ExploitCard({ exploit: e }: { exploit: Exploit }) {
  const { t } = useI18n();
  return (
    <article className="finding-card">
      <div className="finding-card-head">
        <span className="finding-category">
          {musterLabel(e.muster)} · {t("exploitSeverity")}: {RISK_LABELS[e.severity]} ·{" "}
          {t("exploitEffort")}: {RISK_LABELS[e.aufwand]}
        </span>
      </div>
      <h3 className="finding-title">{e.titel}</h3>
      <dl className="exploit-facts">
        <dt>{t("exploitActor")}</dt>
        <dd>{e.akteur}</dd>
        <dt>{t("exploitSteps")}</dt>
        <dd>
          <ol>
            {e.schritte.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </dd>
        <dt>{t("exploitGain")}</dt>
        <dd>{e.vorteil}</dd>
        <dt>{t("exploitMissing")}</dt>
        <dd>{e.fehlende_absicherung}</dd>
      </dl>
      <blockquote className="finding-quote">{e.quote}</blockquote>
      <Feedback kind="exploit" id={e.id} />
    </article>
  );
}

export function DetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  // Back to the list as it was left: the list passes its filters and page.
  const listSearch = (useLocation().state as { listSearch?: string } | null)?.listSearch;
  const backTo = `/${listSearch ?? ""}`;

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
        <Link className="back-link" to={backTo}>
          ← {t("backToList")}
        </Link>
      </div>
    );
  }

  if (error || !bill) {
    return (
      <div className="detail-message">
        <p className="notice notice-error">{t("errorGeneric")}</p>
        <Link className="back-link" to={backTo}>
          ← {t("backToList")}
        </Link>
      </div>
    );
  }

  const documents = bill.analysis_documents ?? [];
  const related = bill.related_documents ?? [];
  const craftFindings = bill.findings.filter(
    (f) => !CONSTITUTIONAL_CATEGORIES.has(f.category),
  );
  const constitutionalFindings = bill.findings.filter((f) =>
    CONSTITUTIONAL_CATEGORIES.has(f.category),
  );
  const exploits = bill.exploits ?? [];
  const analyzedIds = new Set(documents.map((d) => d.document_id));
  const docTypeLabel = (typ: string) =>
    typ === "gesetzentwurf"
      ? t("docTypeGesetzentwurf")
      : typ === "beschlussempfehlung"
        ? t("docTypeBeschlussempfehlung")
        : typ;

  return (
    <article className="detail-page">
      <Link className="back-link" to={backTo}>
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
        {craftFindings.length === 0 ? (
          <p className="notice">{t("noFindings")}</p>
        ) : (
          <div className="finding-list">
            {craftFindings.map((f) => (
              <FindingCard key={f.id} finding={f} documents={documents} />
            ))}
          </div>
        )}
      </section>

      {constitutionalFindings.length > 0 && (
        <section className="detail-constitutional">
          <h2>{t("constitutionalHeading")}</h2>
          <p className="section-note">{t("constitutionalNote")}</p>
          <div className="finding-list">
            {constitutionalFindings.map((f) => (
              <FindingCard key={f.id} finding={f} documents={documents} />
            ))}
          </div>
        </section>
      )}

      {bill.redteamed_at && (
        <details className="detail-exploits">
          <summary>
            <span className="experimental-tag">{t("exploitsExperimental")}</span>
            {t("exploitsHeading")}{" "}
            <span className="exploit-count">({exploits.length})</span>
          </summary>
          <p className="section-note">{t("exploitsNote")}</p>
          {exploits.length === 0 ? (
            <p className="notice">{t("noExploits")}</p>
          ) : (
            <>
              {bill.redteam_summary && (
                <p className="exploit-summary">{bill.redteam_summary}</p>
              )}
              <div className="finding-list">
                {exploits.map((e) => (
                  <ExploitCard key={e.id} exploit={e} />
                ))}
              </div>
            </>
          )}
          <p className="exploit-run">
            {t("methodModel")}: {bill.redteam_model ?? "–"} · {t("methodPromptVersion")}:{" "}
            {bill.redteam_prompt_version ?? "–"} · {t("methodAnalyzedAt")}:{" "}
            {formatDateTime(bill.redteamed_at)}
          </p>
        </details>
      )}

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
