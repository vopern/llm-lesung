import { useState } from "react";
import { postFeedback, type FeedbackKind, type FeedbackVerdict } from "../api";
import { useI18n } from "../i18n";

const MAX_TEXT_CHARS = 2000;

// A reader's verdict on one finding or exploit: two buttons that open a small
// form. What was sent is remembered only until the page is left.
export function Feedback({ kind, id }: { kind: FeedbackKind; id: number }) {
  const { t } = useI18n();
  const [verdict, setVerdict] = useState<FeedbackVerdict | null>(null);
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  if (state === "sent") {
    return <p className="feedback feedback-thanks">{t("feedbackThanks")}</p>;
  }

  const choice = (value: FeedbackVerdict, label: string) => (
    <button
      type="button"
      className={verdict === value ? "active" : undefined}
      aria-pressed={verdict === value}
      onClick={() => setVerdict(value)}
    >
      {label}
    </button>
  );

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    if (!verdict) return;
    setState("sending");
    postFeedback(kind, id, verdict, text)
      .then(() => setState("sent"))
      .catch(() => setState("error"));
  };

  return (
    <form className="feedback" onSubmit={send}>
      <div className="feedback-choices">
        <span className="feedback-label">{t("feedbackQuestion")}</span>
        {choice("up", t("feedbackUp"))}
        {choice("down", t("feedbackDown"))}
      </div>
      {verdict && (
        <div className="feedback-form">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={MAX_TEXT_CHARS}
            rows={3}
            placeholder={t("feedbackPlaceholder")}
            aria-label={t("feedbackPlaceholder")}
          />
          <p className="feedback-hint">{t("feedbackHint")}</p>
          <div className="feedback-actions">
            <button type="submit" className="feedback-send" disabled={state === "sending"}>
              {t("feedbackSend")}
            </button>
            <button
              type="button"
              onClick={() => {
                setVerdict(null);
                setState("idle");
              }}
            >
              {t("feedbackCancel")}
            </button>
            {state === "error" && (
              <span className="feedback-error" role="alert">
                {t("feedbackError")}
              </span>
            )}
          </div>
        </div>
      )}
    </form>
  );
}
