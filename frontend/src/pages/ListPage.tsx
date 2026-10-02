import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchBills,
  fetchMeta,
  type BillsResponse,
  type Meta,
  type Risk,
} from "../api";
import { useI18n } from "../i18n";
import { formatDate } from "../format";
import { FindingChips } from "../components/FindingChips";

const PAGE_SIZE = 20;

const RISK_ORDER: Risk[] = ["hoch", "mittel", "niedrig"];

export function ListPage() {
  const { t } = useI18n();
  const navigate = useNavigate();

  const [meta, setMeta] = useState<Meta | null>(null);
  const [risk, setRisk] = useState<Risk | null>(null);
  const [status, setStatus] = useState<string>("");
  const [search, setSearch] = useState<string>(""); // raw input value
  const [q, setQ] = useState<string>(""); // debounced value used for fetching
  const [page, setPage] = useState(1);

  // Debounce the search input so we don't fetch on every keystroke. Once q
  // catches up with search, the effect re-runs and bails without a timer.
  useEffect(() => {
    if (search === q) return;
    const handle = setTimeout(() => {
      setQ(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(handle);
  }, [search, q]);

  const [data, setData] = useState<BillsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // Meta (counts + status options) loaded once.
  useEffect(() => {
    let alive = true;
    fetchMeta()
      .then((m) => {
        if (alive) setMeta(m);
      })
      .catch(() => {
        /* counts simply stay unknown; list still works */
      });
    return () => {
      alive = false;
    };
  }, []);

  // Bills reloaded whenever a filter or the page changes.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    fetchBills({ risk, status: status || null, q: q || null, page, page_size: PAGE_SIZE })
      .then((d) => {
        if (alive) setData(d);
      })
      .catch(() => {
        if (alive) setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [risk, status, q, page]);

  function toggleRisk(next: Risk) {
    setPage(1);
    setRisk((cur) => (cur === next ? null : next));
  }

  const cardLabel: Record<Risk, string> = {
    hoch: t("riskHigh"),
    mittel: t("riskMedium"),
    niedrig: t("riskLow"),
  };

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);
  const hasPrev = page > 1;
  const hasNext = to < total;

  return (
    <div className="list-page">
      <h2 className="cards-heading">{t("severityHeading")}</h2>
      <div className="risk-cards">
        {RISK_ORDER.map((r) => (
          <button
            key={r}
            type="button"
            className={`risk-card risk-card-${r} ${risk === r ? "active" : ""}`}
            aria-pressed={risk === r}
            onClick={() => toggleRisk(r)}
          >
            <span className="risk-card-count">{meta?.counts[r] ?? "–"}</span>
            <span className="risk-card-label">{cardLabel[r]}</span>
          </button>
        ))}
      </div>

      <div className="filters">
        <input
          type="search"
          className="search-input"
          value={search}
          placeholder={t("searchPlaceholder")}
          aria-label={t("searchPlaceholder")}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="status-select"
          value={status}
          aria-label={t("colStatus")}
          onChange={(e) => {
            setPage(1);
            setStatus(e.target.value);
          }}
        >
          <option value="">{t("allStatuses")}</option>
          {meta?.statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="notice">{t("loading")}</p>
      ) : error ? (
        <p className="notice notice-error">{t("errorGeneric")}</p>
      ) : items.length === 0 ? (
        <p className="notice empty-state">{t("emptyState")}</p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="bills-table">
              <thead>
                <tr>
                  <th>{t("colNumber")}</th>
                  <th>{t("colTitle")}</th>
                  <th>{t("colStatus")}</th>
                  <th>{t("colFindings")}</th>
                  <th>{t("colUpdated")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((b) => (
                  <tr
                    key={b.id}
                    className="bill-row"
                    tabIndex={0}
                    role="link"
                    onClick={() => navigate(`/bill/${b.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        navigate(`/bill/${b.id}`);
                      }
                    }}
                  >
                    <td className="col-number">{b.dokumentnummer}</td>
                    <td className="col-title">{b.titel}</td>
                    <td className="col-status">{b.status ?? "–"}</td>
                    <td className="col-findings">
                      <FindingChips bill={b} />
                    </td>
                    <td className="col-updated">{formatDate(b.aktualisiert)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button
              type="button"
              disabled={!hasPrev}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              {t("prev")}
            </button>
            <span className="page-range">
              {from}–{to} {t("rangeOf")} {total}
            </span>
            <button
              type="button"
              disabled={!hasNext}
              onClick={() => setPage((p) => p + 1)}
            >
              {t("next")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
