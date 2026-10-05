import type { Bill, Severity } from "../api";
import { CATEGORY_LABELS, RISK_LABELS } from "../format";
import { useI18n } from "../i18n";

const SEVERITIES: Severity[] = ["hoch", "mittel", "niedrig"];

// The finding counts of one bill, as colored count chips. The three severity
// chips cover the risk-bearing categories only, so the highest one always
// matches the bill's severity rating; the constitutional categories are
// reported separately because they never enter that rating.
export function FindingChips({ bill }: { bill: Bill }) {
  const { t } = useI18n();

  // risk IS NULL means "not yet analyzed" — most of the corpus. That must not
  // look like "analyzed, nothing found".
  if (bill.risk === null) {
    return <span className="findings-none">{t("notAnalyzed")}</span>;
  }

  const counts: Record<Severity, number> = {
    hoch: bill.findings_hoch,
    mittel: bill.findings_mittel,
    niedrig: bill.findings_niedrig,
  };
  const shown = SEVERITIES.filter((s) => counts[s] > 0);

  if (shown.length === 0 && bill.findings_verfassung === 0) {
    return <span className="findings-zero">{t("zeroFindings")}</span>;
  }

  return (
    <span className="finding-chips">
      {shown.map((s) => (
        <span
          key={s}
          className={`chip chip-${s}`}
          title={`${counts[s]} × ${RISK_LABELS[s]}`}
        >
          {counts[s]}
        </span>
      ))}
      {bill.findings_verfassung > 0 && (
        <span
          className="chip chip-verfassung"
          title={`${CATEGORY_LABELS.verfassungsrisiko} / ${CATEGORY_LABELS.kompetenz}`}
        >
          {bill.findings_verfassung}
        </span>
      )}
    </span>
  );
}
