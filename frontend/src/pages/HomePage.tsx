import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Layout } from "../components/Layout";
import { MIN_QUERY, useSearch, type SearchState } from "../hooks/useSearch";
import { clearRecent, loadRecent, type RecentAirport } from "../lib/recent";

export const PILOT_AIRPORTS = [
  { code: "EGLL", label: "London Heathrow · LHR" },
  { code: "RJBB", label: "Osaka Kansai · KIX" },
  { code: "KJFK", label: "New York JFK · JFK" },
];

function statusText(state: SearchState): string {
  switch (state.status) {
    case "idle":
      return `Type at least ${MIN_QUERY} characters.`;
    case "loading":
      return "Searching…";
    case "error":
      return "Search isn’t available right now.";
    case "done":
      if (state.results.length === 0) {
        return `No airports match “${state.query}”. Try a city, an airport name or a 3–4 letter code.`;
      }
      return `${state.results.length} ${state.results.length === 1 ? "airport" : "airports"} found`;
  }
}

function Shortcuts({ recent, onClear }: { recent: RecentAirport[]; onClear: () => void }) {
  return (
    <div className="shortcuts">
      {recent.length > 0 && (
        <div>
          <div className="shortcuts-heading">
            <h2>Recently viewed</h2>
            <button type="button" className="link-button" onClick={onClear}>
              Clear
            </button>
          </div>
          <ul className="pill-list">
            {recent.map((airport) => (
              <li key={airport.code}>
                <Link to={`/airport/${airport.code}`} className="pill">
                  {airport.name}
                  {airport.iata ? ` · ${airport.iata}` : ` · ${airport.code}`}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <h2 className="shortcuts-title">Try one of our pilot airports</h2>
        <ul className="pill-list">
          {PILOT_AIRPORTS.map((airport) => (
            <li key={airport.code}>
              <Link to={`/airport/${airport.code}`} className="pill">
                {airport.label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function HomePage() {
  const [params] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [recent, setRecent] = useState<RecentAirport[]>(() => loadRecent());
  const { state, retry } = useSearch(query);
  const navigate = useNavigate();

  useEffect(() => {
    document.title = "ClearFlight – airport weather, explained";
  }, []);

  const results = state.status === "done" ? state.results : [];

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const first = results[0];
    if (first) navigate(`/airport/${first.code}`);
  }

  return (
    <Layout>
      <div className="container hero">
        <h1 className="hero-title">Check the weather at an airport</h1>
        <p className="hero-lead">
          The latest observed weather, how recent it is, and an experimental conditions index with its reasons.
        </p>
        <form role="search" onSubmit={onSubmit}>
          <label htmlFor="airport-search" className="field-label">
            Airport name, city or code
          </label>
          <input
            id="airport-search"
            className="search-input"
            type="search"
            autoComplete="off"
            placeholder="e.g. Heathrow, Osaka, JFK"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-describedby="search-status"
          />
        </form>
        <p id="search-status" className="search-status" aria-live="polite">
          {statusText(state)}
        </p>
        {state.status === "error" && (
          <button type="button" className="button" onClick={retry}>
            Retry
          </button>
        )}
        {results.length > 0 && (
          <ul className="results" aria-label="Search results">
            {results.map((airport) => (
              <li key={airport.code}>
                <Link to={`/airport/${airport.code}`} className="result">
                  <span className="result-text">
                    <span className="result-name">{airport.name}</span>
                    <span className="result-place">{[airport.city, airport.country].filter(Boolean).join(", ")}</span>
                  </span>
                  <span className="result-codes">
                    {[airport.icao, airport.iata].filter(Boolean).map((code) => (
                      <span key={code} className="code-chip">
                        {code}
                      </span>
                    ))}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <Shortcuts
          recent={recent}
          onClear={() => {
            clearRecent();
            setRecent([]);
          }}
        />
      </div>
    </Layout>
  );
}
