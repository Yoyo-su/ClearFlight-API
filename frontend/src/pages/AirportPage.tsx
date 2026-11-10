import { useEffect } from "react";
import { useLocation, useNavigate, useParams } from "react-router";

import type { ConditionsResponse } from "../api/types";
import { AirportHeading } from "../components/AirportHeading";
import { ConditionsCard } from "../components/ConditionsCard";
import { ForecastSection } from "../components/ForecastSection";
import { Layout, SearchForm } from "../components/Layout";
import { ObservationCard } from "../components/ObservationCard";
import { useConditions, useForecast, type ConditionsState, type Failure, type ForecastState } from "../hooks/useConditions";
import { useNow } from "../hooks/useNow";
import { conditionsFor, viewAt } from "../lib/ageing";
import { formatAgo, formatDuration, formatUtcTime, minutesSince } from "../lib/format";
import { rememberAirport } from "../lib/recent";

interface PanelProps {
  title: string;
  body: string;
  action?: { label: string; onClick: () => void; disabled?: boolean };
  search?: boolean;
}

function Panel({ title, body, action, search }: PanelProps) {
  return (
    <section className="card panel" aria-labelledby="panel-heading">
      <h2 id="panel-heading" className="panel-title">
        {title}
      </h2>
      <p className="panel-body">{body}</p>
      {action && (
        <div>
          <button type="button" className="button" onClick={action.onClick} disabled={action.disabled}>
            {action.label}
          </button>
        </div>
      )}
      {search && <SearchForm id="panel-search" visibleLabel />}
    </section>
  );
}

function Loading({ code, slow }: { code: string; slow: boolean }) {
  return (
    <>
      <h1 className="code-heading">{code}</h1>
      <p role="status" className="muted">
        {slow ? "Still waiting for the weather service…" : "Loading weather…"}
      </p>
      <div className="cards" aria-hidden="true">
        {[0, 1].map((card) => (
          <div key={card} className="card skeleton-card">
            <div className="skeleton" style={{ width: "55%", height: 18 }} />
            <div className="skeleton" style={{ width: "40%", height: 48 }} />
            <div className="skeleton" style={{ width: "90%" }} />
            <div className="skeleton" style={{ width: "80%" }} />
          </div>
        ))}
      </div>
    </>
  );
}

function FailureView({ code, failure, state, retry, now }: {
  code: string;
  failure: Failure;
  state: ConditionsState;
  retry: () => void;
  now: Date;
}) {
  const heading = <h1 className="code-heading">{code}</h1>;
  if (failure.kind === "error" && failure.status === 400) {
    return (
      <>
        {heading}
        <Panel
          title="That isn’t an airport code"
          body={`“${code}” isn’t an airport code. Use a 3-letter IATA code (like LHR) or a 4-character ICAO code (like EGLL).`}
          search
        />
      </>
    );
  }
  if (failure.kind === "error" && failure.status === 404) {
    return (
      <>
        {heading}
        <Panel title="Airport not found" body={`We couldn’t find an airport with the code ${code}.`} search />
      </>
    );
  }
  if (failure.kind === "network") {
    return (
      <>
        {heading}
        <Panel title="Can’t reach ClearFlight" body="Check your connection, then try again." action={{ label: "Try again", onClick: retry }} />
      </>
    );
  }
  if (failure.status === 503) {
    const seconds = state.retryAt === null ? 0 : Math.max(0, Math.ceil((state.retryAt - now.getTime()) / 1000));
    return (
      <>
        {heading}
        <Panel
          title="Lots of people are checking the weather right now"
          body={seconds > 0 ? `Trying again automatically in ${seconds} s…` : "Please try again."}
          action={{ label: "Try again", onClick: retry, disabled: seconds > 0 }}
        />
      </>
    );
  }
  return (
    <>
      {heading}
      <Panel
        title="The weather service didn’t respond"
        body="This is usually temporary. Try again in a moment."
        action={{ label: "Try again", onClick: retry }}
      />
    </>
  );
}

function SourceRow({ data, state, refresh, now }: {
  data: ConditionsResponse;
  state: ConditionsState;
  refresh: () => void;
  now: Date;
}) {
  const observation = data.observation;
  if (!observation) return null;
  const coolingDown = now.getTime() < state.cooldownUntil;
  return (
    <div className="source-row">
      <div className="source-text">
        <span>Source: NOAA Aviation Weather Center</span>
        <span>
          Observed {formatUtcTime(observation.observed_at)} · Fetched {formatUtcTime(observation.fetched_at)}
        </span>
      </div>
      <div className="source-actions">
        <span aria-live="polite">{coolingDown ? "Checked just now" : "Updates every 5 minutes while open"}</span>
        <button type="button" className="button button-ghost" onClick={refresh} disabled={coolingDown}>
          Refresh
        </button>
      </div>
    </div>
  );
}

function DataView({ data, state, refresh, now, forecast, retryForecast }: {
  data: ConditionsResponse;
  state: ConditionsState;
  refresh: () => void;
  now: Date;
  forecast: ForecastState;
  retryForecast: () => void;
}) {
  const view = viewAt(data, now);
  const coolingDown = now.getTime() < state.cooldownUntil;
  const refreshAction = { label: "Refresh", onClick: refresh, disabled: coolingDown };
  const failedNote = state.refreshFailed && data.last_observed_at && (
    <p role="status" className="notice notice-neutral">
      Couldn’t update just now — showing the report from {formatUtcTime(data.last_observed_at)}.
    </p>
  );

  let body;
  if (view === "no-station") {
    body = (
      <Panel
        title="No weather station"
        body="This airport doesn’t have a weather station that publishes METAR reports, so ClearFlight can’t show its weather."
      />
    );
  } else if (view === "no-report") {
    body = (
      <Panel
        title="No current weather report"
        body="The weather station at this airport hasn’t published a report recently. ClearFlight checks again every 5 minutes while this page is open."
        action={refreshAction}
      />
    );
  } else if (view === "too-old") {
    const last = data.last_observed_at;
    body = (
      <Panel
        title="No current weather report"
        body={
          last
            ? `The latest weather report (${formatUtcTime(last)}, ${formatAgo(last, now)}) is too old to show.`
            : "The latest weather report is too old to show."
        }
        action={refreshAction}
      />
    );
  } else if (data.observation) {
    const observation = data.observation;
    const stale = view === "stale";
    body = (
      <>
        {stale ? (
          <p role="status" className="notice notice-stale">
            This report is {formatDuration(minutesSince(observation.observed_at, now))} old (
            {formatUtcTime(observation.observed_at)}), so it isn’t scored. Showing it for reference.
          </p>
        ) : (
          <p role="status" className="status-line">
            <span className="status-dot" aria-hidden="true" />
            Observed {formatAgo(observation.observed_at, now)} · {formatUtcTime(observation.observed_at)}
          </p>
        )}
        <div className="cards">
          <ConditionsCard conditions={conditionsFor(data, view)} stale={stale} />
          <ObservationCard observation={observation} />
        </div>
        <SourceRow data={data} state={state} refresh={refresh} now={now} />
      </>
    );
  }
  return (
    <>
      <AirportHeading airport={data.airport} now={now} />
      {failedNote}
      {body}
      <ForecastSection state={forecast} retry={retryForecast} now={now} timeZone={data.airport.timezone} />
    </>
  );
}

export function AirportPage() {
  const { code: param = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  // After the URL is rewritten to the canonical code (D8), keep using the code
  // that was requested, so the rewrite doesn't trigger a second fetch.
  const requested = (location.state as { requested?: string } | null)?.requested ?? param.toUpperCase();
  const { state, refresh: refreshConditions, retry } = useConditions(requested);
  const { state: forecast, refresh: refreshForecast, retry: retryForecast } = useForecast(requested);
  const refresh = () => {
    refreshConditions();
    refreshForecast();
  };
  const data = state.data;
  const forecastData = forecast.data;
  const now = useNow(
    state.retryAt !== null ? 1000 : 15000,
    [
      data?.current_until ? Date.parse(data.current_until) : null,
      data?.stale_until ? Date.parse(data.stale_until) : null,
      state.cooldownUntil || null,
      state.retryAt,
      // Forecast hours leave the screen as they end (CF-008 §5).
      forecastData?.forecast ? Date.parse(forecastData.forecast.valid_to) : null,
      ...(forecastData?.hours ?? []).map((hour) => Date.parse(hour.end)),
    ],
    data,
  );

  useEffect(() => {
    if (!data) return;
    const airport = data.airport;
    document.title = `${airport.name} (${airport.code}) – ClearFlight`;
    rememberAirport({ code: airport.code, iata: airport.iata, name: airport.name });
    if (param !== airport.code) {
      navigate(`/airport/${airport.code}`, { replace: true, state: { requested } });
    }
  }, [data, param, requested, navigate]);

  let content;
  if (data) {
    content = (
      <DataView data={data} state={state} refresh={refresh} now={now} forecast={forecast} retryForecast={retryForecast} />
    );
  }
  else if (state.failure) {
    // A forecast that loaded stays available when the observation fails.
    content = (
      <>
        <FailureView code={param.toUpperCase()} failure={state.failure} state={state} retry={retry} now={now} />
        {forecastData?.data_status === "available" && (
          <ForecastSection state={forecast} retry={retryForecast} now={now} timeZone={forecastData.airport.timezone} />
        )}
      </>
    );
  }
  else content = <Loading code={param.toUpperCase()} slow={state.slow} />;

  return (
    <Layout headerSearch>
      <div className="container stack">{content}</div>
    </Layout>
  );
}
