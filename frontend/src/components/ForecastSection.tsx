import { useState } from "react";

import type { ForecastHour, ForecastResponse } from "../api/types";
import type { ForecastState } from "../hooks/useConditions";
import { forecastViewAt } from "../lib/ageing";
import { isValidTimeZone } from "../lib/clock";
import { formatUtcTime } from "../lib/format";
import { FactorRow, LEVEL_WORDS } from "./ConditionsCard";

// The forecast outlook (CF-008 spec §1, §5; F1–F5). Forecast values are always
// labelled as forecast and styled apart from the observed index (F4): outlined
// cells, no filled level chips, and never on the observed card.

function hourLabel(iso: string, timeZone: string | null): string {
  const zone = timeZone && isValidTimeZone(timeZone) ? timeZone : "UTC";
  return new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(
    new Date(iso),
  );
}

/** The worst possible state worth showing: "up to N" or unknown (F1, F5). */
function worstPossible(hour: ForecastHour) {
  if (hour.possible.length === 0) return null;
  const unknown = hour.possible.find((p) => p.conditions.score === null);
  if (unknown) return { score: null, label: unknown.label };
  return hour.possible.reduce((worst, p) => ((p.conditions.score ?? 0) > (worst.score ?? 0) ? { score: p.conditions.score, label: p.label } : worst), {
    score: hour.possible[0]!.conditions.score,
    label: hour.possible[0]!.label,
  });
}

function HourCell({ hour, timeZone, selected, onSelect, id }: {
  hour: ForecastHour;
  timeZone: string | null;
  selected: boolean;
  onSelect: () => void;
  id: string;
}) {
  const time = hourLabel(hour.start, timeZone);
  if (hour.status === "not_yet_valid" || !hour.prevailing) {
    return (
      <li className="forecast-hour forecast-hour-pending">
        <span className="forecast-time">{time}</span>
        <span className="forecast-note">Forecast not yet valid</span>
      </li>
    );
  }
  const conditions = hour.prevailing.conditions;
  const possible = worstPossible(hour);
  const level = conditions.level;
  return (
    <li className={`forecast-hour forecast-level-${level}`}>
      <button type="button" className="forecast-hour-button" aria-expanded={selected} aria-controls={id} onClick={onSelect}>
        <span className="forecast-time">{time}</span>
        <span className="forecast-score">
          {conditions.score === null ? "Unknown" : `${conditions.score} / 10`}
          <span className="forecast-level"> {conditions.score === null ? "" : LEVEL_WORDS[level]}</span>
        </span>
        {hour.prevailing.changing && <span className="forecast-note">Changing</span>}
        {possible && (
          <span className="forecast-possible">
            {possible.score === null ? "May be worse (details unknown)" : `Up to ${possible.score} / 10`}
            <span className="forecast-note"> {possible.label}</span>
          </span>
        )}
      </button>
    </li>
  );
}

function HourDetails({ hour, timeZone, id }: { hour: ForecastHour; timeZone: string | null; id: string }) {
  const prevailing = hour.prevailing;
  if (!prevailing) return null;
  const local = timeZone && isValidTimeZone(timeZone);
  const range = `${hourLabel(hour.start, timeZone)}–${hourLabel(hour.end, timeZone)}`;
  return (
    <div id={id} className="forecast-details" role="region" aria-label={`Forecast details ${range}`}>
      <p className="forecast-range">
        {range} {local ? "local" : "UTC"}
        {local && ` · ${formatUtcTime(hour.start).replace(" UTC", "")}–${formatUtcTime(hour.end)}`}
      </p>
      <p className="explanation">{prevailing.conditions.explanation}</p>
      {prevailing.changing && (
        <p className="muted small">Conditions are forecast to change during this hour; the worse of them is shown.</p>
      )}
      <ul className="factors" aria-label="Forecast factors">
        {prevailing.conditions.factors.map((factor) => (
          <FactorRow key={factor.name} factor={factor} scored />
        ))}
      </ul>
      {hour.possible.map((p) => (
        <p key={p.label} className="forecast-possible-detail">
          <strong>
            {p.conditions.score === null ? "May be worse" : `Up to ${p.conditions.score} / 10`} ({p.label}):
          </strong>{" "}
          {p.conditions.explanation}
        </p>
      ))}
    </div>
  );
}

function Hours({ data, hours, timeZone }: { data: ForecastResponse; hours: ForecastHour[]; timeZone: string | null }) {
  const [selected, setSelected] = useState<string | null>(null);
  const shown = hours.find((h) => h.start === selected) ?? null;
  const forecast = data.forecast;
  return (
    <>
      <ol className="forecast-hours" aria-label="Hourly forecast">
        {hours.map((hour) => (
          <HourCell
            key={hour.start}
            hour={hour}
            timeZone={timeZone}
            selected={hour.start === selected}
            onSelect={() => setSelected(hour.start === selected ? null : hour.start)}
            id="forecast-details"
          />
        ))}
      </ol>
      {shown && <HourDetails hour={shown} timeZone={timeZone} id="forecast-details" />}
      {forecast && (
        <div className="source-row">
          <div className="source-text">
            <span>Source: {forecast.source}</span>
            <span>
              Issued {formatUtcTime(forecast.issued_at)} · Valid until {formatUtcTime(forecast.valid_to)}
            </span>
          </div>
        </div>
      )}
      {forecast && (
        <details className="raw">
          <summary>Raw forecast (TAF)</summary>
          <pre>{forecast.raw_text}</pre>
        </details>
      )}
    </>
  );
}

export function ForecastSection({ state, retry, now, timeZone }: {
  state: ForecastState;
  retry: () => void;
  now: Date;
  timeZone: string | null;
}) {
  const data = state.data;
  let body;
  if (!data) {
    if (state.failure) {
      body = (
        <>
          <p className="panel-body">The forecast couldn’t be loaded just now.</p>
          <div>
            <button type="button" className="button button-ghost" onClick={retry}>
              Try again
            </button>
          </div>
        </>
      );
    } else {
      body = (
        <p role="status" className="muted">
          Loading forecast…
        </p>
      );
    }
  } else {
    const view = forecastViewAt(data, now);
    if (view.kind === "no-station") return null; // the conditions panel already says so
    if (view.kind === "no-forecast") body = <p className="panel-body">No forecast is available for this airport right now.</p>;
    else if (view.kind === "expired") body = <p className="panel-body">The latest forecast has expired.</p>;
    else body = <Hours data={data} hours={view.hours} timeZone={timeZone} />;
  }
  return (
    <section className="card forecast" aria-labelledby="forecast-heading">
      <div className="card-title-row">
        <h2 id="forecast-heading" className="card-title">
          Forecast (next 12 hours)
        </h2>
        <span className="muted small">Forecast conditions index · not observed weather</span>
      </div>
      {state.refreshFailed && data?.forecast && (
        <p role="status" className="notice notice-neutral">
          Couldn’t update the forecast just now — showing the forecast issued {formatUtcTime(data.forecast.issued_at)}.
        </p>
      )}
      {body}
      <p className="disclaimer">{data?.disclaimer ?? "A forecast, not observed weather. It does not predict delays, cancellations or flight safety."}</p>
    </section>
  );
}
