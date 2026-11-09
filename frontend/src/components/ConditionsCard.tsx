import type { Conditions, Factor, Level } from "../api/types";

// The experimental conditions index (spec §3.2.5, D2): the number and the
// level word always appear together, colour is never the only signal, and
// there is no green anywhere in the index.

export const LEVEL_WORDS: Record<Level, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  severe: "Severe",
  unknown: "Unknown",
};

const FACTOR_NAMES: Record<Factor["name"], string> = {
  wind: "Wind",
  visibility: "Visibility",
  ceiling: "Ceiling",
  weather: "Weather",
};

export function levelOf(score: number | null): Level {
  if (score === null) return "unknown";
  if (score <= 2) return "low";
  if (score <= 5) return "moderate";
  if (score <= 7) return "high";
  return "severe";
}

export function FactorRow({ factor, scored }: { factor: Factor; scored: boolean }) {
  const unknown = factor.score === null;
  const level = levelOf(factor.score);
  return (
    <li className="factor">
      <span className="factor-name">{FACTOR_NAMES[factor.name]}</span>
      <span className="factor-body">
        <span className={`factor-track${unknown ? " factor-track-unknown" : ""}`} aria-hidden="true">
          {!unknown && (
            <span
              className={`factor-fill ${scored ? `level-fill-${level}` : "level-fill-unscored"}`}
              style={{ width: `${Math.max((factor.score ?? 0) * 10, 3)}%` }}
            />
          )}
        </span>
        <span className="factor-detail">{factor.detail}</span>
      </span>
      <span className={`factor-score${scored && !unknown ? ` level-text-${level}` : ""}`}>
        {unknown ? "Unknown" : `${factor.score} / 10`}
      </span>
    </li>
  );
}

export function ConditionsCard({ conditions, stale }: { conditions: Conditions; stale: boolean }) {
  const scored = conditions.score !== null;
  const chipLevel: Level = stale ? "unknown" : conditions.level;
  return (
    <section className="card" aria-labelledby="index-heading">
      <div className="card-title-row">
        <h2 id="index-heading" className="card-title">
          Experimental conditions index
        </h2>
        <span className="muted small">v{conditions.version} · observed weather only</span>
      </div>
      <div className="score-row">
        {scored ? (
          <>
            <span className="score-number">{conditions.score}</span>
            <span className="score-outof">/ 10</span>
          </>
        ) : (
          <span className="score-word">{stale ? "Not scored" : "Unknown"}</span>
        )}
        <span className={`level-chip level-chip-${chipLevel}`}>{stale ? "Stale" : LEVEL_WORDS[conditions.level]}</span>
      </div>
      {stale && <p className="score-note">Not scored: this report is too old to score.</p>}
      <p className="explanation">{conditions.explanation}</p>
      {conditions.factors.length > 0 && (
        <ul className="factors" aria-label="Factors">
          {conditions.factors.map((factor) => (
            <FactorRow key={factor.name} factor={factor} scored={!stale} />
          ))}
        </ul>
      )}
      <p className="disclaimer">{conditions.disclaimer}</p>
    </section>
  );
}
