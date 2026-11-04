import type { ReactNode } from "react";
import { Link } from "react-router";

export const FOOTER_DISCLAIMER =
  "ClearFlight shows observed weather only. It is not a forecast and does not predict delays, cancellations or flight safety.";

function Wordmark() {
  return (
    <Link to="/" className="wordmark">
      <svg
        width="28"
        height="28"
        viewBox="0 0 28 28"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M7 19h13a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.3 3.3 0 0 0 7 19z" />
        <path d="M3 9l6 2 5-5 1.5 1-3 5 5 1.5" />
      </svg>
      <span>ClearFlight</span>
    </Link>
  );
}

/** A plain GET form to the home page's search (header, error and not-found pages). */
export function SearchForm({ id, visibleLabel = false }: { id: string; visibleLabel?: boolean }) {
  return (
    <form className={visibleLabel ? "inline-search" : "header-search"} role="search" action="/" method="get">
      <label htmlFor={id} className={visibleLabel ? "field-label" : "visually-hidden"}>
        {visibleLabel ? "Airport name, city or code" : "Search airports"}
      </label>
      <input id={id} name="q" type="search" placeholder="Search airports" autoComplete="off" />
    </form>
  );
}

export function Layout({ children, headerSearch = false }: { children: ReactNode; headerSearch?: boolean }) {
  return (
    <div className="page">
      <header className="site-header">
        <div className="container header-row">
          <Wordmark />
          {headerSearch ? <SearchForm id="header-search" /> : <span className="strapline">Airport weather, explained</span>}
        </div>
      </header>
      <main className="site-main" id="main">
        {children}
      </main>
      <footer className="site-footer">
        <div className="container footer-text">
          <p>
            Weather: <a href="https://aviationweather.gov/">NOAA Aviation Weather Center</a>. Airport data:{" "}
            <a href="https://ourairports.com/data/">OurAirports</a>. Timezones: IANA tz database.
          </p>
          <p>{FOOTER_DISCLAIMER}</p>
        </div>
      </footer>
    </div>
  );
}
