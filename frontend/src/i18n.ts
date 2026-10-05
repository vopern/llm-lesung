// Minimal i18n for UI chrome only. Data (bill titles, findings, statuses)
// always stays German — intentional, matching the reference site.
import { createContext, useContext } from "react";

export type Lang = "de" | "en";

export type StringKey =
  | "subtitle"
  | "navBills"
  | "navAbout"
  | "riskHigh"
  | "riskMedium"
  | "riskLow"
  | "notAnalyzed"
  | "zeroFindings"
  | "statAnalyzed"
  | "statVerfassung"
  | "statVerfassungSub"
  | "allStatuses"
  | "searchPlaceholder"
  | "colNumber"
  | "colTitle"
  | "colStatus"
  | "colFindings"
  | "colUpdated"
  | "prev"
  | "next"
  | "rangeOf"
  | "pages"
  | "emptyState"
  | "noMatches"
  | "loading"
  | "errorGeneric"
  | "notFoundTitle"
  | "notFoundBody"
  | "backToList"
  | "pdfLink"
  | "initiator"
  | "status"
  | "date"
  | "worstFinding"
  | "summaryHeading"
  | "findingsHeading"
  | "noFindings"
  | "quotePage"
  | "quoteContext"
  | "constitutionalHeading"
  | "constitutionalNote"
  | "exploitsHeading"
  | "exploitsExperimental"
  | "exploitsNote"
  | "noExploits"
  | "exploitActor"
  | "exploitSteps"
  | "exploitGain"
  | "exploitMissing"
  | "exploitSeverity"
  | "exploitEffort"
  | "methodHeading"
  | "methodPromptVersion"
  | "methodModel"
  | "methodAnalyzedAt"
  | "methodDocuments"
  | "methodDocumentsAmended"
  | "docTypeGesetzentwurf"
  | "docTypeBeschlussempfehlung"
  | "relatedNotAnalyzed"
  | "feedbackQuestion"
  | "feedbackUp"
  | "feedbackDown"
  | "feedbackPlaceholder"
  | "feedbackHint"
  | "feedbackSend"
  | "feedbackCancel"
  | "feedbackThanks"
  | "feedbackError"
  | "disclaimer"
  | "footer"
  | "evalLink"
  | "privacyLink"
  | "evalTitle"
  | "evalReports"
  | "evalNoReports";

const de: Record<StringKey, string> = {
  subtitle: "KI-Analyse von Gesetzentwürfen des Deutschen Bundestags",
  navBills: "Gesetzentwürfe",
  navAbout: "Info",
  riskHigh: "Hoch",
  riskMedium: "Mittel",
  riskLow: "Niedrig",
  notAnalyzed: "nicht analysiert",
  zeroFindings: "keine Befunde",
  statAnalyzed: "analysiert",
  statVerfassung: "Verfassungsrisiko",
  statVerfassungSub: "zählt nicht zum Schweregrad",
  allStatuses: "Alle Status",
  searchPlaceholder: "Titel durchsuchen …",
  colNumber: "Nummer",
  colTitle: "Titel",
  colStatus: "Status",
  colFindings: "Befunde",
  colUpdated: "Aktualisiert",
  prev: "Zurück",
  next: "Weiter",
  rangeOf: "von",
  pages: "Seiten",
  emptyState: "Noch keine Analysen — Pipeline ausführen.",
  noMatches: "Keine Gesetzentwürfe für diese Auswahl.",
  loading: "Wird geladen …",
  errorGeneric: "Fehler beim Laden der Daten.",
  notFoundTitle: "Gesetzentwurf nicht gefunden",
  notFoundBody: "Dieser Gesetzentwurf existiert nicht oder wurde entfernt.",
  backToList: "Zurück zur Übersicht",
  pdfLink: "Drucksache als PDF",
  initiator: "Urheber",
  status: "Status",
  date: "Datum",
  worstFinding: "Schwerster Befund",
  summaryHeading: "Gesamteinschätzung",
  findingsHeading: "Befunde",
  quotePage: "Seite",
  quoteContext: "Im Kontext",
  constitutionalHeading: "Verfassungsrisiko und Kompetenz",
  constitutionalNote:
    "Diese Befunde werden ausgewiesen, zählen aber nicht zum Schweregrad.",
  exploitsHeading: "Missbrauchsszenarien",
  exploitsExperimental: "Experimentell",
  exploitsNote:
    "Ein zweiter Durchlauf fragt, wie jemand den Entwurf in böser Absicht ausnutzen könnte, auch wenn er handwerklich fehlerfrei ist. Die Szenarien sind ungeprüft und zählen nicht zum Schweregrad.",
  noExploits: "Keine Missbrauchsszenarien gefunden.",
  exploitActor: "Akteur",
  exploitSteps: "Vorgehen",
  exploitGain: "Vorteil",
  exploitMissing: "Fehlende Absicherung",
  exploitSeverity: "Schwere",
  exploitEffort: "Aufwand",
  noFindings: "Keine konkreten Befunde.",
  methodHeading: "Methodik",
  methodPromptVersion: "Prompt-Version",
  methodModel: "Modell",
  methodAnalyzedAt: "Analysiert am",
  methodDocuments: "Analysierte Dokumente",
  methodDocumentsAmended:
    "Die Befunde beziehen sich auf den Entwurf in der Fassung der Beschlussempfehlung.",
  docTypeGesetzentwurf: "Gesetzentwurf",
  docTypeBeschlussempfehlung: "Beschlussempfehlung",
  relatedNotAnalyzed: "in der Analyse nicht berücksichtigt",
  feedbackQuestion: "Stimmt das?",
  feedbackUp: "Trifft zu",
  feedbackDown: "Trifft nicht zu",
  feedbackPlaceholder: "Anmerkung (optional)",
  feedbackHint:
    "Gespeichert werden Ihre Bewertung und Ihr Text, ohne Angaben zu Ihrer Person. Bitte keine personenbezogenen Daten eintragen.",
  feedbackSend: "Senden",
  feedbackCancel: "Abbrechen",
  feedbackThanks: "Danke, die Rückmeldung ist gespeichert.",
  feedbackError: "Senden fehlgeschlagen. Bitte die Seite neu laden.",
  disclaimer:
    "Die Befunde stammen von einem Sprachmodell. Sie sind ungeprüft und können falsch oder unvollständig sein. Dies ist ein Experiment im maschinellen Lesen: keine Autorität, keine Rechtsberatung und keine politische Empfehlung.",
  footer:
    "Datenquelle: Deutscher Bundestag – DIP · Kein offizielles Angebot des Bundestags",
  evalLink: "Evaluation",
  privacyLink: "Datenschutz",
  evalTitle: "Evaluation des Analyseprompts",
  evalReports: "Berichte",
  evalNoReports: "Noch keine Berichte veröffentlicht.",
};

const en: Record<StringKey, string> = {
  subtitle: "AI analysis of German Bundestag draft bills",
  navBills: "Draft bills",
  navAbout: "About",
  riskHigh: "High",
  riskMedium: "Medium",
  riskLow: "Low",
  notAnalyzed: "not analyzed",
  zeroFindings: "no findings",
  statAnalyzed: "analyzed",
  statVerfassung: "Constitutional risk",
  statVerfassungSub: "not part of the severity",
  allStatuses: "All statuses",
  searchPlaceholder: "Search titles …",
  colNumber: "Number",
  colTitle: "Title",
  colStatus: "Status",
  colFindings: "Findings",
  colUpdated: "Updated",
  prev: "Back",
  next: "Next",
  rangeOf: "of",
  pages: "Pages",
  emptyState: "No analyses yet — run the pipeline.",
  noMatches: "No draft bills match this selection.",
  loading: "Loading …",
  errorGeneric: "Failed to load data.",
  notFoundTitle: "Draft bill not found",
  notFoundBody: "This draft bill does not exist or was removed.",
  backToList: "Back to overview",
  pdfLink: "Drucksache as PDF",
  initiator: "Initiator",
  status: "Status",
  date: "Date",
  worstFinding: "Worst finding",
  summaryHeading: "Overall assessment",
  findingsHeading: "Findings",
  quotePage: "page",
  quoteContext: "In context",
  constitutionalHeading: "Constitutional risk and competence",
  constitutionalNote:
    "These findings are reported but are not part of the severity.",
  exploitsHeading: "Abuse scenarios",
  exploitsExperimental: "Experimental",
  exploitsNote:
    "A second pass asks how someone acting in bad faith could exploit the draft, even if it is technically flawless. The scenarios are unreviewed and are not part of the severity.",
  noExploits: "No abuse scenarios found.",
  exploitActor: "Actor",
  exploitSteps: "Steps",
  exploitGain: "Gain",
  exploitMissing: "Missing safeguard",
  exploitSeverity: "Severity",
  exploitEffort: "Effort",
  noFindings: "No concrete findings.",
  methodHeading: "Methodology",
  methodPromptVersion: "Prompt version",
  methodModel: "Model",
  methodAnalyzedAt: "Analyzed at",
  methodDocuments: "Analyzed documents",
  methodDocumentsAmended:
    "Findings refer to the draft as amended by the committee recommendation.",
  docTypeGesetzentwurf: "Draft bill",
  docTypeBeschlussempfehlung: "Committee recommendation",
  relatedNotAnalyzed: "not used in the analysis",
  feedbackQuestion: "Is this right?",
  feedbackUp: "Correct",
  feedbackDown: "Not correct",
  feedbackPlaceholder: "Comment (optional)",
  feedbackHint:
    "Your rating and text are stored, with nothing about you. Please enter no personal data.",
  feedbackSend: "Send",
  feedbackCancel: "Cancel",
  feedbackThanks: "Thanks, your feedback is saved.",
  feedbackError: "Sending failed. Please reload the page.",
  disclaimer:
    "The findings are generated by a language model. They are unreviewed and may be wrong or incomplete. This is an experiment in machine reading: not an authority, and not legal advice or a political recommendation.",
  footer:
    "Data source: Deutscher Bundestag – DIP · Not an official Bundestag service",
  evalLink: "Evaluation",
  privacyLink: "Privacy",
  evalTitle: "Evaluation of the analysis prompt",
  evalReports: "Reports",
  evalNoReports: "No reports published yet.",
};

export const DICTS: Record<Lang, Record<StringKey, string>> = { de, en };

export const STORAGE_KEY = "llm-lesung.lang";

export function loadLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "de" || v === "en") return v;
  } catch {
    // ignore (e.g. storage disabled)
  }
  return "de";
}

export function saveLang(lang: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // ignore
  }
}

export interface I18nContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: StringKey) => string;
}

export const I18nContext = createContext<I18nContextValue | null>(null);

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
