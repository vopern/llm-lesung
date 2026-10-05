import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchMeta } from "../api";
import { useI18n } from "../i18n";
import { CATEGORY_LABELS } from "../format";

const LAWLAB_URL = "https://lawlab.ilves.ai";
const WIRED_URL =
  "https://www.wired.com/story/the-28-million-dollar-mistake-that-inspired-estonias-ai-fuckup-finder/";

// Category descriptions (eight methodology categories). German label stays fixed;
// the surrounding explanation follows the UI language.
const CATEGORY_DESC: Record<keyof typeof CATEGORY_LABELS, { de: string; en: string }> = {
  referenz: {
    de: "fehlerhafte oder ins Leere gehende Verweise auf Paragrafen, Absätze oder Gesetze",
    en: "broken or wrong references to sections, paragraphs or laws",
  },
  widerspruch: {
    de: "widersprüchliche Formulierungen zwischen Entwurfstext und Begründung oder im Text selbst",
    en: "contradictory wording between the draft text and its reasoning, or within the text",
  },
  rechenfehler: {
    de: "Rechenfehler in Beträgen, Prozentsätzen oder Summen",
    en: "arithmetic errors in amounts, percentages or totals",
  },
  datum: {
    de: "unmögliche oder inkonsistente Daten und Fristen",
    en: "impossible or inconsistent dates and deadlines",
  },
  vollstaendigkeit: {
    de: "Unvollständigkeit, etwa fehlende Anlagen oder nicht definierte Begriffe",
    en: "incompleteness, e.g. missing annexes or undefined terms",
  },
  unklarheit: {
    de: "erhebliche Mehrdeutigkeit mit praktischen Folgen",
    en: "significant ambiguity with practical consequences",
  },
  verfassungsrisiko: {
    de: "verfassungsrechtliche Defekte, bei denen ein benannter Prüfmaßstab ausgelöst ist — etwa Bestimmtheitsgebot, Rückwirkung oder Sonderrecht gegen eine bestimmte Meinung",
    en: "constitutional defects where a named doctrinal test is triggered — e.g. the certainty requirement, retroactivity, or a law singling out one opinion",
  },
  kompetenz: {
    de: "fehlende Gesetzgebungskompetenz sowie neue Aufgaben oder Kosten für Länder und Kommunen ohne Kosten- oder Konnexitätsregelung",
    en: "missing legislative competence, or new tasks and costs for the Länder and municipalities without a cost-sharing provision",
  },
};

export function AboutPage() {
  const { t, lang } = useI18n();
  const de = lang === "de";

  // The contact address is server configuration; without one the section stays hidden.
  const [contactEmail, setContactEmail] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchMeta()
      .then((meta) => {
        if (!cancelled) setContactEmail(meta.contact_email);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <article className="about-page prose">
      <h1>{de ? "Über LLM-Lesung" : "About LLM-Lesung"}</h1>

      <p>
        {de ? (
          <>
            LLM-Lesung liest die Gesetzentwürfe des Deutschen Bundestags mit einem
            Sprachmodell gegen und sucht nach vermeidbaren Fehlern: ins Leere
            laufende Verweise, Widersprüche zwischen Gesetzestext und Begründung,
            Rechen- und Datumsfehler, fehlende Teile und Unklarheiten mit
            praktischen Folgen. Jeder Befund zitiert die betroffene Stelle, damit er
            sich am Original nachprüfen lässt. Der Name spielt auf die Lesungen im
            Parlament an — hier kommt eine weitere hinzu, durch eine KI.
          </>
        ) : (
          <>
            LLM-Lesung reads the draft bills of the German Bundestag with a language
            model and looks for avoidable errors: references that point nowhere,
            contradictions between the legal text and its reasoning, arithmetic and
            date errors, missing parts, and ambiguities with practical consequences.
            Every finding quotes the passage concerned, so it can be checked against
            the original. The name alludes to the readings in parliament — this adds
            one more, done by an AI.
          </>
        )}
      </p>

      <p>
        {de ? (
          <>
            Die Idee stammt aus Estland: Das{" "}
            <a href={LAWLAB_URL} target="_blank" rel="noopener noreferrer">LawLab</a>{" "}
            prüft Gesetzentwürfe mit KI und weist auf Fehler hin, bevor sie Gesetz
            werden (Hintergrund: <a href={WIRED_URL} target="_blank" rel="noopener noreferrer">Reportage bei WIRED</a>).
            Gesetze werden unter Zeitdruck geschrieben und später nachgebessert –
            ein Gegenleser, der früh auf Fehler hinweist, kann hier helfen.
          </>
        ) : (
          <>
            The idea comes from Estonia: the {" "}
            <a href={LAWLAB_URL} target="_blank" rel="noopener noreferrer">LawLab</a>{" "}
            checks draft bills with AI and flags mistakes before they become law
            (background: <a href={WIRED_URL} target="_blank" rel="noopener noreferrer">WIRED story</a>).
            Laws are written under time pressure and patched later – a proofreader
            that flags mistakes early can help.
          </>
        )}
      </p>

      <p>
        {de ? (
          <>
            LLM-Lesung versteht sich als Studie, nicht als fertiges Werkzeug. Es
            geht nicht darum, einzelne Fehler herauszustellen. Die Befunde sollen
            zeigen, ob KI das Fehlerrisiko in der Gesetzgebung senken kann – und wo
            ihre Grenzen liegen. Deshalb wird auch gemessen, was das Modell findet
            und was es übersieht: mit Evaluationen an bekannten Mängeln und mit
            Rückmeldungen von Leserinnen und Lesern.
          </>
        ) : (
          <>
            LLM-Lesung sees itself as a study, not a finished tool. The point is
            not to single out individual errors. The findings are meant to show
            whether AI can lower the risk of errors in lawmaking – and where its
            limits are. That is why it also measures what the model finds and what
            it misses: with evaluations on known defects and with feedback from
            readers.
          </>
        )}
      </p>

      <h2>{de ? "Datenquelle" : "Data source"}</h2>
      <p>
        {de ? (
          <>
            Grundlage sind die Gesetzentwürfe der laufenden 21. Wahlperiode aus dem
            Dokumentations- und Informationssystem für Parlamentsmaterialien (DIP)
            des Deutschen Bundestags, dazu die Beschlussempfehlungen der Ausschüsse
            zu diesen Entwürfen. Die Volltexte stammen aus den öffentlichen
            Drucksachen-PDFs.
          </>
        ) : (
          <>
            The basis are the draft bills of the current 21st electoral term from
            the Documentation and Information System for Parliamentary Materials
            (DIP) of the German Bundestag, together with the committees&apos;
            recommendations for decision on them. Full texts come from the public
            Drucksache PDFs.
          </>
        )}
      </p>

      <h2>{de ? "Methodik" : "Methodology"}</h2>
      <p>
        {de ? (
          <>
            Der vollständige Text jedes Gesetzentwurfs wird, zusammen mit seinen
            Beschlussempfehlungen, von Claude auf acht Fehlerkategorien geprüft.
            Jeder Befund erhält eine Schwere (hoch, mittel oder niedrig); der
            Schweregrad eines Entwurfs ist die höchste Schwere seiner handwerklichen
            Befunde — er beschreibt den schwersten Befund, keine Bewertung des
            Entwurfs als Ganzes. Sehr umfangreiche Entwürfe (über eine Million
            Zeichen) werden derzeit nicht analysiert. Befunde zu Verfassungsrisiko und
            Kompetenz werden ausgewiesen, fließen aber nicht in die Einstufung ein:
            sie beruhen auf einer rechtlichen Wertung, die eine KI nicht
            zuverlässig genug trifft, um ein Urteil über einen Entwurf zu tragen.
          </>
        ) : (
          <>
            The full text of each draft bill, together with its recommendations for
            decision, is analyzed by Claude for eight error categories. Each finding
            gets a severity (hoch, mittel or niedrig); a bill&apos;s severity is the
            highest severity among its craft findings — it describes the worst
            finding, not a rating of the bill as a whole. Very long bills (over one
            million characters) are currently not analyzed.
            Constitutional and competence findings are reported but stay out of the
            rating: they rest on a legal judgment an AI does not make reliably
            enough to carry a verdict on a bill.
          </>
        )}
      </p>
      <ul className="category-list">
        {(Object.keys(CATEGORY_LABELS) as (keyof typeof CATEGORY_LABELS)[]).map(
          (key) => (
            <li key={key}>
              <strong>{CATEGORY_LABELS[key]}</strong>: {CATEGORY_DESC[key][lang]}
            </li>
          )
        )}
      </ul>

      <h2>{de ? "Evaluation" : "Evaluation"}</h2>
      <p>
        {de ? (
          <>
            Wie zuverlässig der Prompt bekannte Mängel findet, wird an Testfällen mit
            dokumentierter Vorgeschichte gemessen. Siehe technische <Link to="/evaluation">Evaluation</Link>.
          </>
        ) : (
          <>
            How reliably the prompt finds known defects is measured on test cases with a
            documented history. Runs, individual cases and model output are on the technical{" "}
            <Link to="/evaluation">evaluation</Link> page.
          </>
        )}
      </p>

      <h2>{de ? "Haftungsausschluss" : "Disclaimer"}</h2>
      <p>{t("disclaimer")}</p>

      {contactEmail && (
        <>
          <h2>{de ? "Kontakt" : "Contact"}</h2>
          <p>
            <a href={`mailto:${contactEmail}`}>{contactEmail}</a>
          </p>
        </>
      )}
    </article>
  );
}
