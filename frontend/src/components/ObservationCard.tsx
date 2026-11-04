import type { Observation } from "../api/types";
import {
  formatCeiling,
  formatCloud,
  formatGusts,
  formatPressure,
  formatTemperature,
  formatVisibility,
  formatWeather,
  formatWind,
} from "../lib/format";

const MISSING = new Set(["Not reported", "None reported"]);

export function ObservationCard({ observation }: { observation: Observation }) {
  const rows: [string, string][] = [
    ["Temperature", formatTemperature(observation.temperature_c)],
    ["Dew point", formatTemperature(observation.dewpoint_c)],
    ["Wind", formatWind(observation)],
    ["Gusts", formatGusts(observation.wind_gust_kt)],
    ["Visibility", formatVisibility(observation.visibility_m, observation.visibility_at_least)],
    ["Cloud", formatCloud(observation)],
    ["Ceiling", formatCeiling(observation)],
    ["Weather", formatWeather(observation.weather_phenomena)],
    ["Pressure", formatPressure(observation.pressure_hpa)],
  ];
  return (
    <section className="card" aria-labelledby="obs-heading">
      <h2 id="obs-heading" className="card-title">
        Observed weather
      </h2>
      <dl className="obs-list">
        {rows.map(([label, value]) => (
          <div key={label} className="obs-row">
            <dt>{label}</dt>
            <dd className={MISSING.has(value) ? "muted" : undefined}>{value}</dd>
          </div>
        ))}
      </dl>
      {observation.raw_text && (
        <details className="raw">
          <summary>Raw METAR report</summary>
          <pre>{observation.raw_text}</pre>
        </details>
      )}
    </section>
  );
}
