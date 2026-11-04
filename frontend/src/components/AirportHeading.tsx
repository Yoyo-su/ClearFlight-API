import type { Airport } from "../api/types";
import { isValidTimeZone, readClock } from "../lib/clock";

function Clock({ label, timeZone, now }: { label: string; timeZone: string; now: Date }) {
  const reading = readClock(timeZone, now);
  return (
    <div className="clock">
      <div className="clock-label">{label}</div>
      <div className="clock-time">
        <time dateTime={now.toISOString()}>{reading.time}</time>
      </div>
      <div className="clock-sub">{timeZone === "UTC" ? reading.date : `${reading.date} · ${reading.zone}`}</div>
    </div>
  );
}

export function AirportHeading({ airport, now }: { airport: Airport; now: Date }) {
  const place = [airport.city, airport.country].filter(Boolean).join(", ");
  const codes = [airport.icao, airport.iata].filter((c): c is string => Boolean(c));
  const hasZone = airport.timezone !== null && isValidTimeZone(airport.timezone);
  return (
    <div className="airport-heading">
      <div className="airport-title">
        <h1>{airport.name}</h1>
        <div className="airport-meta">
          {codes.map((code) => (
            <span key={code} className="code-chip">
              {code}
            </span>
          ))}
          {place && <span className="muted">{place}</span>}
        </div>
      </div>
      <div className="clocks">
        {hasZone ? (
          <Clock label="Local time" timeZone={airport.timezone as string} now={now} />
        ) : (
          <div className="clock">
            <div className="clock-label">Local time</div>
            <div className="clock-sub">Local time unavailable for this airport</div>
          </div>
        )}
        <Clock label="UTC" timeZone="UTC" now={now} />
      </div>
    </div>
  );
}
