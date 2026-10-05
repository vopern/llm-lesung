import { useEffect, useState } from "react";
import { fetchMeta } from "../api";
import { useI18n } from "../i18n";

export function PrivacyPage() {
  const { lang } = useI18n();
  const de = lang === "de";

  // The contact address is server configuration; without one the line stays hidden.
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
      <h1>{de ? "Datenschutzerklärung" : "Privacy policy"}</h1>

      <p>
        {de
          ? "Diese Website setzt keine Cookies und nutzt kein Tracking."
          : "This website sets no cookies and uses no tracking."}
      </p>

      <p>
        {de ? (
          <>
            Beim Aufruf verarbeiten Cloudflare (Auslieferung, USA, zertifiziert
            unter dem EU-US Data Privacy Framework) und Amazon Web Services
            (Server in Frankfurt am Main) als Auftragsverarbeiter die Daten, die
            Ihr Browser übermittelt, darunter die IP-Adresse. Rechtsgrundlage ist
            das berechtigte Interesse, die Website sicher bereitzustellen (Art. 6
            Abs. 1 Buchst. f DSGVO). Der Server selbst speichert keine
            IP-Adressen.
          </>
        ) : (
          <>
            When you visit, Cloudflare (delivery, USA, certified under the EU-US
            Data Privacy Framework) and Amazon Web Services (server in Frankfurt am
            Main) process, as processors, the data your browser sends, including
            the IP address. The legal basis is the legitimate interest in providing
            the website securely (Art. 6(1)(f) GDPR). The server itself stores no
            IP addresses.
          </>
        )}
      </p>

      <p>
        {de ? (
          <>
            Wenn Sie einen Befund bewerten, speichert der Server Ihre Bewertung,
            Ihren Text, den Zeitpunkt und den bewerteten Befund, um die Analyse
            zu verbessern (Art. 6 Abs. 1 Buchst. f DSGVO). Er speichert dabei
            weder IP-Adresse noch andere Angaben zu Ihrer Person. Bitte tragen
            Sie keine personenbezogenen Daten in das Textfeld ein.
          </>
        ) : (
          <>
            When you rate a finding, the server stores your rating, your text,
            the time and the finding you rated, in order to improve the analysis
            (Art. 6(1)(f) GDPR). It stores neither your IP address nor anything
            else about you. Please enter no personal data in the text field.
          </>
        )}
      </p>

      <p>
        {de ? (
          <>
            Sie haben die Rechte aus Art. 15 bis 21 DSGVO (unter anderem Auskunft,
            Löschung und Widerspruch) und können sich bei einer
            Datenschutz-Aufsichtsbehörde beschweren.
          </>
        ) : (
          <>
            You have the rights under Art. 15 to 21 GDPR (including access, erasure
            and objection) and can lodge a complaint with a data protection
            supervisory authority.
          </>
        )}
        {contactEmail && (
          <>
            {" "}
            {de ? "Verantwortlich ist der Betreiber dieser Website:" : "The operator of this website is the controller:"}{" "}
            <a href={`mailto:${contactEmail}`}>{contactEmail}</a>
          </>
        )}
      </p>
    </article>
  );
}
