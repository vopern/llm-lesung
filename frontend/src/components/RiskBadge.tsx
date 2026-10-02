import type { Risk, Severity } from "../api";
import { RISK_LABELS } from "../format";

// A colored badge for a bill risk or a finding severity (same scale/colors).
export function RiskBadge({ level }: { level: Risk | Severity | null }) {
  if (!level) {
    return <span className="badge badge-none">–</span>;
  }
  return <span className={`badge badge-${level}`}>{RISK_LABELS[level]}</span>;
}
