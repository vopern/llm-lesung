// API types matching Contract 4 (LLM_LESUNG_PLAN.md) and the SQLite schema
// (Contract 1). Data fields stay German by design.

export type Risk = "hoch" | "mittel" | "niedrig";
export type Severity = "hoch" | "mittel" | "niedrig";
export type Category =
  | "referenz"
  | "widerspruch"
  | "rechenfehler"
  | "datum"
  | "vollstaendigkeit"
  | "unklarheit"
  | "verfassungsrisiko"
  | "kompetenz";

// One row of GET /api/bills
export interface Bill {
  id: string;
  dokumentnummer: string;
  titel: string;
  status: string | null;
  risk: Risk | null;
  datum: string | null;
  aktualisiert: string | null;
  // All findings, constitutional ones included.
  finding_count: number;
  // Risk-bearing findings only, so these reconcile with `risk`.
  findings_hoch: number;
  findings_mittel: number;
  findings_niedrig: number;
  // verfassungsrisiko + kompetenz: reported, but excluded from `risk`.
  findings_verfassung: number;
}

export interface BillsResponse {
  items: Bill[];
  total: number;
  page: number;
  page_size: number;
}

// Where a finding's quote stands in the documents the analysis read.
export interface QuoteLocation {
  document_id: string;
  page: number; // 1-based page of the PDF
  before: string;
  match: string; // the quote as the document spells it
  after: string;
}

export interface Finding {
  id: number; // changes with every re-analysis
  severity: Severity;
  category: Category;
  title: string;
  description: string;
  quote: string | null;
  location: QuoteLocation | null; // null: no quote, or not found
}

// One attack from the adversarial pass: what a bad-faith actor gets out of the
// draft as written.
export interface Exploit {
  id: number; // changes with every re-run of the pass
  muster: string;
  akteur: string;
  titel: string;
  schritte: string[];
  vorteil: string;
  aufwand: Severity;
  quote: string;
  fehlende_absicherung: string;
  severity: Severity;
}

// One document the stored analysis read.
export interface AnalysisDocument {
  document_id: string;
  typ: "gesetzentwurf" | "beschlussempfehlung";
  dokumentnummer: string;
  datum: string | null;
  pdf_url: string;
  pdf_hash: string | null;
  aktualisiert: string | null;
  text_chars: number | null;
}

// A related Drucksache DIP lists for the bill's Vorgang, e.g. a
// Beschlussempfehlung. Whether the analysis read it is `analysis_documents`.
export interface RelatedDocument {
  document_id: string;
  typ: "beschlussempfehlung";
  dokumentnummer: string;
  titel: string | null;
  datum: string | null;
  aktualisiert: string | null;
  pdf_url: string;
  pdf_hash: string | null;
}

// GET /api/bills/{id} — all bill columns plus findings.
export interface BillDetail {
  id: string;
  dokumentnummer: string;
  wahlperiode: number;
  titel: string;
  urheber: string | null;
  datum: string | null;
  aktualisiert: string | null;
  status: string | null;
  vorgang_id: string | null;
  pdf_url: string;
  pdf_hash: string | null;
  text_chars: number | null;
  risk: Risk | null;
  summary: string | null;
  prompt_version: string | null;
  model: string | null;
  analyzed_at: string | null;
  findings: Finding[];
  // Empty for unanalyzed bills and analyses that predate the column.
  analysis_documents: AnalysisDocument[];
  related_documents: RelatedDocument[];
  // The adversarial pass; `redteamed_at` null means it has not run.
  exploits: Exploit[];
  redteam_summary: string | null;
  redteam_prompt_version: string | null;
  redteam_model: string | null;
  redteamed_at: string | null;
}

export interface Meta {
  counts: {
    hoch: number;
    mittel: number;
    niedrig: number;
    unanalysiert: number;
    total: number;
    // Bills with a verfassungsrisiko/kompetenz finding; overlaps the risk counts.
    verfassung: number;
  };
  statuses: string[];
  prompt_version: string;
  model: string;
  last_analyzed_at: string | null;
  // Null when the server has no CONTACT_EMAIL configured.
  contact_email: string | null;
}

// Raised when a fetch returns a non-2xx status. `status` lets callers
// distinguish 404 (bill not found) from other failures.
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(url: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" } });
  } catch (e) {
    throw new ApiError(0, `Netzwerkfehler: ${(e as Error).message}`);
  }
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status} für ${url}`);
  }
  return (await res.json()) as T;
}

export interface BillsQuery {
  risk?: Risk | null;
  status?: string | null;
  q?: string | null;
  verfassung?: boolean;
  page?: number;
  page_size?: number;
}

export function fetchBills(query: BillsQuery = {}): Promise<BillsResponse> {
  const params = new URLSearchParams();
  if (query.risk) params.set("risk", query.risk);
  if (query.status) params.set("status", query.status);
  if (query.q) params.set("q", query.q);
  if (query.verfassung) params.set("verfassung", "1");
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.page_size ?? 20));
  return getJson<BillsResponse>(`/api/bills?${params.toString()}`);
}

export function fetchBill(id: string): Promise<BillDetail> {
  return getJson<BillDetail>(`/api/bills/${encodeURIComponent(id)}`);
}

export function fetchMeta(): Promise<Meta> {
  return getJson<Meta>("/api/meta");
}

// --- Reader feedback (POST /api/feedback) -----------------------------------

export type FeedbackKind = "finding" | "exploit";
export type FeedbackVerdict = "up" | "down";

export async function postFeedback(
  kind: FeedbackKind,
  id: number,
  verdict: FeedbackVerdict,
  text: string,
): Promise<void> {
  const res = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, id, verdict, text }),
  });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status} für /api/feedback`);
}

// --- Evaluation reports (GET /api/eval) -------------------------------------
// HTML reports placed by hand in the server's evaluation folder.

export interface EvalReport {
  path: string;
  title: string;
  modified: string;
}

export function fetchEvalReports(): Promise<EvalReport[]> {
  return getJson<EvalReport[]>("/api/eval");
}

export function evalReportUrl(path: string): string {
  return `/api/eval/reports/${path.split("/").map(encodeURIComponent).join("/")}`;
}
