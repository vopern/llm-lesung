import type { Category, Risk } from "./api";

// Category labels stay German (data-side labels), per the reference behavior.
export const CATEGORY_LABELS: Record<Category, string> = {
  referenz: "Verweisfehler",
  widerspruch: "Widerspruch",
  rechenfehler: "Rechenfehler",
  datum: "Datum/Frist",
  vollstaendigkeit: "Vollständigkeit",
  unklarheit: "Unklarheit",
  verfassungsrisiko: "Verfassungsrisiko",
  kompetenz: "Kompetenz",
};

// Reported, but excluded from the bill's severity.
export const CONSTITUTIONAL_CATEGORIES: ReadonlySet<string> = new Set([
  "verfassungsrisiko",
  "kompetenz",
]);

// Attack patterns of the adversarial pass.
const MUSTER_LABELS: Record<string, string> = {
  adressatenwahl: "Adressatenwahl",
  entkopplung: "Entkopplung",
  schwellenwert: "Schwellenwert",
  definitionsmacht: "Definitionsmacht",
  zeitfenster: "Zeitfenster",
  nachweisluecke: "Nachweislücke",
  sanktionsarithmetik: "Sanktionsarithmetik",
  kumulation: "Kumulation",
  anwendungsbereich: "Anwendungsbereich",
  vollzugsspielraum: "Vollzugsspielraum",
};

export function musterLabel(muster: string): string {
  return MUSTER_LABELS[muster] ?? muster;
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category as Category] ?? category;
}

// German risk labels used on badges (data-side, always German).
export const RISK_LABELS: Record<Risk, string> = {
  hoch: "Hoch",
  mittel: "Mittel",
  niedrig: "Niedrig",
};

export function riskLabel(risk: Risk | null): string {
  return risk ? RISK_LABELS[risk] : "–";
}

// Format an ISO date/timestamp as a short German date. Falls back to the raw
// string if it is not parseable, and to "–" when absent.
export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("de-DE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "–";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("de-DE", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
