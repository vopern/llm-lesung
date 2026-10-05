import { useI18n } from "../i18n";

const WINDOW = 5;

// Page numbers to show: first, last and a run of WINDOW pages around the
// current one, shifted inwards at either end so the run never shrinks.
// A gap that would hide a single page shows that page instead of an ellipsis.
export function pageWindow(current: number, total: number): (number | "gap")[] {
  const start = Math.max(1, Math.min(current - Math.floor(WINDOW / 2), total - WINDOW + 1));
  const wanted = new Set([1, total]);
  for (let p = start; p < start + WINDOW; p++) wanted.add(p);
  const pages = [...wanted].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const result: (number | "gap")[] = [];
  let prev = 0;
  for (const p of pages) {
    if (p - prev === 2) result.push(prev + 1);
    else if (p - prev > 2) result.push("gap");
    result.push(p);
    prev = p;
  }
  return result;
}

interface Props {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPage }: Props) {
  const { t } = useI18n();
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <nav className="pagination" aria-label={t("pages")}>
      <span className="page-range">
        {from}–{to} {t("rangeOf")} {total}
      </span>
      {totalPages > 1 && (
        <div className="page-buttons">
          <button
            type="button"
            aria-label={t("prev")}
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            ‹
          </button>
          {pageWindow(page, totalPages).map((p, i) =>
            p === "gap" ? (
              <span key={`gap-${i}`} className="page-gap">
                …
              </span>
            ) : (
              <button
                key={p}
                type="button"
                className={p === page ? "active" : ""}
                aria-current={p === page ? "page" : undefined}
                onClick={() => onPage(p)}
              >
                {p}
              </button>
            )
          )}
          <button
            type="button"
            aria-label={t("next")}
            disabled={page >= totalPages}
            onClick={() => onPage(page + 1)}
          >
            ›
          </button>
        </div>
      )}
    </nav>
  );
}
