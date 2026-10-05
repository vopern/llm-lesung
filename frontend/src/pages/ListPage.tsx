import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
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
import { Pagination } from "../components/Pagination";

const PAGE_SIZE = 20;

const RISK_ORDER: Risk[] = ["hoch", "mittel", "niedrig"];

function parseRisk(value: string | null): Risk | null {
  return RISK_ORDER.includes(value as Risk) ? (value as Risk) : null;
}

export function ListPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();

  // Filters and page live in the URL, so they survive a visit to a bill and
  // filtered views can be shared.
  const [params, setParams] = useSearchParams();
  const risk = parseRisk(params.get("risk"));
  const verfassung = params.get("verfassung") === "1";
  const status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  const page = Math.max(1, parseInt(params.get("page") ?? "", 10) || 1);

  function update(changes: Record<string, string | null>, replace = false) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(changes)) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        return next;
      },
      { replace }
    );
  }

  const [meta, setMeta] = useState<Meta | null>(null);
  const [search, setSearch] = useState(q); // raw input value

  // Follow the URL when it changes underneath the input (back/forward).
  useEffect(() => {
    setSearch(q);
  }, [q]);

  // Debounce the search input so we don't fetch on every keystroke. Once q
  // catches up with search, the effect re-runs and bails without a timer.
  useEffect(() => {
    if (search === q) return;
    const handle = setTimeout(() => {
      update({ q: search || null, page: null }, true);
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

  // Bills reloaded whenever a filter or the page changes. The previous rows
  // stay on screen, dimmed, until the new ones arrive.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    fetchBills({
      risk,
      status: status || null,
      q: q || null,
      verfassung,
      page,
      page_size: PAGE_SIZE,
    })
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
  }, [risk, status, q, verfassung, page]);

  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  // A page beyond the last one (stale link) falls back to the last page.
  useEffect(() => {
    if (data && data.page === page && page > 1 && data.items.length === 0 && data.total > 0) {
      update({ page: String(Math.ceil(data.total / PAGE_SIZE)) }, true);
    }
  }, [data, page]);

  const listRef = useRef<HTMLDivElement>(null);

  function goToPage(next: number) {
    update({ page: next > 1 ? String(next) : null });
    const el = listRef.current;
    if (el && el.getBoundingClientRect().top < 0) el.scrollIntoView({ block: "start" });
  }

  const cardLabel: Record<Risk, string> = {
    hoch: t("riskHigh"),
    mittel: t("riskMedium"),
    niedrig: t("riskLow"),
  };

  const filtered = risk !== null || verfassung || status !== "" || q !== "";
  const linkState = { listSearch: location.search };

  return (
    <div className="list-page">
      <div className="stat-cards">
        <button
          type="button"
          className={`stat-card ${risk === null && !verfassung ? "active" : ""}`}
          aria-pressed={risk === null && !verfassung}
          onClick={() => update({ risk: null, verfassung: null, page: null })}
        >
          <span className="stat-card-count">{meta?.counts.total ?? "–"}</span>
          <span className="stat-card-label">{t("navBills")}</span>
          <span className="stat-card-sub">
            {meta ? meta.counts.total - meta.counts.unanalysiert : "–"} {t("statAnalyzed")}
          </span>
        </button>
        {RISK_ORDER.map((r) => (
          <button
            key={r}
            type="button"
            className={`stat-card stat-card-${r} ${risk === r ? "active" : ""}`}
            aria-pressed={risk === r}
            onClick={() => update({ risk: risk === r ? null : r, page: null })}
          >
            <span className="stat-card-count">{meta?.counts[r] ?? "–"}</span>
            <span className="stat-card-label">{cardLabel[r]}</span>
            <span className="stat-card-sub">{t("worstFinding")}</span>
          </button>
        ))}
        {/* Same colour as the count chip of these categories in the table. */}
        <button
          type="button"
          className={`stat-card stat-card-verfassung ${verfassung ? "active" : ""}`}
          aria-pressed={verfassung}
          onClick={() => update({ verfassung: verfassung ? null : "1", page: null })}
        >
          <span className="stat-card-count">{meta?.counts.verfassung ?? "–"}</span>
          <span className="stat-card-label">{t("statVerfassung")}</span>
          <span className="stat-card-sub">{t("statVerfassungSub")}</span>
        </button>
      </div>

      <div className="filters" ref={listRef}>
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
          onChange={(e) => update({ status: e.target.value || null, page: null })}
        >
          <option value="">{t("allStatuses")}</option>
          {meta?.statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <p className="notice notice-error">{t("errorGeneric")}</p>
      ) : !data ? (
        <p className="notice">{t("loading")}</p>
      ) : items.length === 0 ? (
        <p className="notice empty-state">{t(filtered ? "noMatches" : "emptyState")}</p>
      ) : (
        <div className={`table-wrap ${loading ? "is-loading" : ""}`} aria-busy={loading}>
          <div className="table-scroll">
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
                    onClick={(e) => {
                      // The number is a real link; let it handle its own clicks.
                      if ((e.target as HTMLElement).closest("a")) return;
                      navigate(`/bill/${b.id}`, { state: linkState });
                    }}
                  >
                    <td className="col-number">
                      <Link to={`/bill/${b.id}`} state={linkState}>
                        {b.dokumentnummer}
                      </Link>
                    </td>
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
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPage={goToPage} />
        </div>
      )}
    </div>
  );
}
