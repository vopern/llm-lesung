import { hasImpressum, useOperator } from "../operator";

// German in both UI languages: the legal label and wording.
export function ImpressumPage() {
  const operator = useOperator();
  if (!hasImpressum(operator)) return null;

  return (
    <article className="about-page prose">
      <h1>Impressum</h1>
      <p>Angaben gemäß § 18 Abs. 1 MStV:</p>
      <p>
        {operator.name}
        {operator.address.map((line) => (
          <span key={line}>
            <br />
            {line}
          </span>
        ))}
      </p>
      {operator.email && (
        <p>
          E-Mail: <a href={`mailto:${operator.email}`}>{operator.email}</a>
        </p>
      )}
    </article>
  );
}
