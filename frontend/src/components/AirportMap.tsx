import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import { fetchAircraft, fetchNearby, fetchRadar } from "../api/client";
import type { AircraftPosition, ConditionsResponse } from "../api/types";
import { useAirportData } from "../hooks/useConditions";
import { useNow } from "../hooks/useNow";
import { aircraftViewAt, conditionsFor, radarFrameAt, stationsAt, viewAt, type StationView } from "../lib/ageing";
import { formatUtcTime } from "../lib/format";
import { LEVEL_WORDS } from "./ConditionsCard";

// The "Live map" section (CF-010 design r3). Nothing is requested until the
// section is near the viewport, and every request is gated on it staying on
// screen with the tab visible (§3). The list below the map carries the same
// information for keyboard and screen-reader users (M6).

const MapView = lazy(() => import("./MapView"));

export const AIRCRAFT_REFRESH_MS = 30_000; // the server's cache period (M5)
export const NEARBY_REFRESH_MS = 10 * 60_000;
export const RADAR_REFRESH_MS = 5 * 60_000;

function useOnScreen<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  // Without IntersectionObserver, treat the section as on screen (tab
  // visibility still gates every request).
  const [onScreen, setOnScreen] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setOnScreen(entry?.isIntersecting ?? false), {
      rootMargin: "200px 0px",
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, onScreen];
}

function secondsAgo(iso: string, now: Date): string {
  const s = Math.max(0, Math.round((now.getTime() - Date.parse(iso)) / 1000));
  return s < 60 ? `${s} s ago` : `${Math.round(s / 60)} min ago`;
}

function altitude(a: AircraftPosition): string {
  if (a.on_ground) return "On ground";
  return a.altitude_ft === null ? "Unknown" : `${a.altitude_ft.toLocaleString("en-GB")} ft`;
}

const REASON_TEXT: Record<string, string> = {
  no_coverage_evidence: "receivers haven't reported traffic here recently",
  stale_feed: "the position feed is delayed",
  unusable_data: "the latest positions couldn't be used",
  busy: "the position service is busy",
};

export function AirportMap({ code, conditions }: { code: string; conditions: ConditionsResponse }) {
  const [sectionRef, onScreen] = useOnScreen<HTMLElement>();
  const [radarOn, setRadarOn] = useState(false);
  const [mapFailed, setMapFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedStation, setSelectedStation] = useState<string | null>(null);
  // Once shown, the map stays mounted while scrolling away (no re-download of
  // the style and tiles); only data requests stop off screen.
  const [seen, setSeen] = useState(false);
  if (onScreen && !seen) setSeen(true); // derived state, updated during render

  const aircraft = useAirportData(code, fetchAircraft, {
    active: onScreen,
    refreshMs: AIRCRAFT_REFRESH_MS,
    cooldownMs: AIRCRAFT_REFRESH_MS,
  });
  const nearby = useAirportData(code, fetchNearby, {
    active: onScreen,
    refreshMs: NEARBY_REFRESH_MS,
    cooldownMs: AIRCRAFT_REFRESH_MS, // the same as the shared Refresh map button
  });
  const radar = useAirportData(code, fetchRadar, { active: onScreen, refreshMs: RADAR_REFRESH_MS });

  const aircraftData = aircraft.state.data;
  const nearbyData = nearby.state.data;
  const radarData = radar.state.data;
  // Every position's own deadline (C4), not just the earliest one.
  const expiries = (aircraftData?.aircraft ?? []).map((a) => Date.parse(a.expires_at));
  const now = useNow(onScreen ? 5000 : 60_000, [
    ...expiries,
    aircraftData?.observed_at ? Date.parse(aircraftData.observed_at) + 60_000 : null,
    aircraftData?.retry_at ? Date.parse(aircraftData.retry_at) : null,
    radarData?.frame ? Date.parse(radarData.frame.current_until) : null,
    ...(nearbyData?.stations ?? []).flatMap((st) => [Date.parse(st.current_until), Date.parse(st.stale_until)]),
    conditions.current_until ? Date.parse(conditions.current_until) : null,
    conditions.stale_until ? Date.parse(conditions.stale_until) : null,
    aircraft.state.cooldownUntil || null,
  ]);

  const view = aircraftData ? aircraftViewAt(aircraftData, now) : null;
  const shown = view?.kind === "aircraft" ? view.aircraft : [];
  const stations: StationView[] = useMemo(() => (nearbyData ? stationsAt(nearbyData.stations, now) : []), [nearbyData, now]);
  const frame = radarOn ? radarFrameAt(radarData, now) : null;
  const area = aircraftData?.area ?? nearbyData?.area ?? null;

  const conditionsView = viewAt(conditions, now);
  // The airport's own score only while its report is current (D-008/D11);
  // stale, too old or missing reports are never scored on the map.
  const own = conditionsView === "current" ? conditionsFor(conditions, conditionsView) : null;
  let ownText: string;
  if (own && own.score !== null) ownText = `${own.score} ${LEVEL_WORDS[own.level]} (observed)`;
  else if (own) ownText = "unknown (observed)";
  else if (conditionsView === "stale" || conditionsView === "too-old") ownText = "old report";
  else ownText = "no current report";
  const airportLabel = `${conditions.airport.code} · ${ownText}`;
  const selectedAircraft = shown.find((a) => a.id === selected) ?? null;
  const coolingDown = now.getTime() < aircraft.state.cooldownUntil;

  let status: string;
  if (!onScreen && !aircraftData) status = "The map loads when you scroll to it.";
  else if (!view) status = aircraft.state.failure ? "Live positions couldn't be loaded." : "Loading live positions…";
  else if (view.kind === "aircraft") {
    status = `${shown.length} aircraft within ${area?.radius_nm ?? 25} nm · ${aircraftData?.source?.name ?? ""}`;
  } else if (view.kind === "no-aircraft") status = `No aircraft reported within ${area?.radius_nm ?? 25} nm.`;
  else if (view.kind === "coverage-unknown")
    status = `Can't confirm traffic near this airport: ${REASON_TEXT[view.reason ?? ""] ?? "coverage isn't known"}.`;
  else if (view.kind === "limit")
    status = view.retryAt ? `Live positions limit reached; try again after ${formatUtcTime(view.retryAt)}.` : "Live positions limit reached.";
  else if (view.kind === "disabled") status = "Live positions aren't available.";
  else if (view.kind === "unavailable") status = "Live positions aren't available right now.";
  else status = "Live positions couldn't be updated.";
  if (aircraft.state.refreshFailed && view?.kind === "aircraft") status += " (couldn't update just now)";

  const hidden = (aircraftData?.withheld ?? 0) + (aircraftData?.excluded ?? 0);
  // Honest empty states: no stations is a claim; unusable or expired reports aren't.
  let nearbyMessage = "Not loaded yet.";
  if (!nearbyData) {
    if (nearby.state.failure) nearbyMessage = "Nearby weather couldn't be loaded.";
  } else if (nearbyData.unavailable_reason === "unusable_data") nearbyMessage = "Nearby reports couldn't be used.";
  else if (nearbyData.unavailable_reason === "reports_too_old" || nearbyData.stations.length > 0)
    nearbyMessage = "Nearby reports are out of date."; // every one has expired on screen
  else nearbyMessage = "No nearby reporting stations.";
  const refreshMap = () => {
    aircraft.refresh();
    nearby.refresh();
  };
  const radarEnabled = radarData?.enabled ?? false;

  return (
    <section ref={sectionRef} className="card map-section" aria-labelledby="map-heading">
      <div className="card-title-row">
        <h2 id="map-heading" className="card-title">
          Live map
        </h2>
        <span className="muted small">Live positions and observed weather</span>
      </div>
      <a className="skip-link" href="#map-list">
        Skip the map, go to the list
      </a>
      <p className="map-status">
        {/* Only state changes are announced; the ticking age isn't. */}
        <span role="status">{status}</span>
        {view?.kind === "aircraft" && aircraftData?.fetched_at && (
          <span className="muted small"> · updated {secondsAgo(aircraftData.fetched_at, now)}</span>
        )}
      </p>
      <div className="map-controls">
        {radarEnabled && (
          <label className="radar-toggle">
            <input type="checkbox" checked={radarOn} onChange={(e) => setRadarOn(e.target.checked)} />
            Radar (observed)
            {radarOn && frame && <span className="muted small"> · {formatUtcTime(frame.time)} · coarse at this zoom</span>}
            {radarOn && !frame && <span className="muted small"> · radar unavailable</span>}
          </label>
        )}
        <button type="button" className="button button-ghost" onClick={refreshMap} disabled={coolingDown || !onScreen}>
          Refresh map
        </button>
      </div>
      <div className="map-frame">
        {mapFailed ? (
          <div className="map-failed">
            <p>The map couldn't load. The list below has the same information.</p>
            <button type="button" className="button button-ghost" onClick={() => setMapFailed(false)}>
              Try the map again
            </button>
          </div>
        ) : seen && area ? (
          <Suspense fallback={<p className="map-failed">Loading map…</p>}>
            <MapView
              center={{ latitude: area.latitude, longitude: area.longitude }}
              radiusNm={aircraftData?.area.radius_nm ?? 25}
              aircraft={shown}
              stations={stations}
              airportLabel={airportLabel}
              radarTileUrl={frame?.tile_url ?? null}
              onSelectAircraft={setSelected}
              onSelectStation={setSelectedStation}
              onError={() => setMapFailed(true)}
            />
          </Suspense>
        ) : (
          <div className="map-placeholder" aria-hidden="true" />
        )}
      </div>
      {selectedAircraft && (
        <p className="map-selected">
          <strong>{selectedAircraft.callsign ?? selectedAircraft.id.toUpperCase()}</strong>: {altitude(selectedAircraft)}
          {selectedAircraft.ground_speed_kt !== null && ` · ${selectedAircraft.ground_speed_kt} kt`} · {selectedAircraft.distance_nm} nm away · position{" "}
          {secondsAgo(selectedAircraft.position_at, now)}
        </p>
      )}
      {(() => {
        const st = stations.find((x) => x.station === selectedStation);
        if (!st) return null;
        const index =
          st.view === "stale" ? "not scored (old report)" : st.conditions.score === null ? "unknown" : `${st.conditions.score} / 10 ${LEVEL_WORDS[st.conditions.level]}`;
        return (
          <p className="map-selected">
            <strong>{st.station}</strong>
            {st.name && ` ${st.name}`}: observed conditions index {index} · observed {formatUtcTime(st.observed_at)} · {st.distance_nm} nm away
          </p>
        );
      })()}
      <p className="muted small map-note">
        Map tiles from OpenFreeMap (© OpenMapTiles © OpenStreetMap contributors){frame && " and radar tiles from RainViewer"};
        loading them sends your IP address and the area viewed to {frame ? "those services" : "that service"}.{" "}
        {aircraftData?.source && (
          <>
            Positions: <a href={aircraftData.source.attribution_url}>{aircraftData.source.name}</a>.{" "}
          </>
        )}
        Weather: NOAA Aviation Weather Center.
        {frame && radarData && (
          <>
            {" "}
            <a href={radarData.attribution_url}>{radarData.attribution}</a>.
          </>
        )}
      </p>

      {/* Scrollable, so focusable for keyboard scrolling; also the skip target. */}
      <div id="map-list" className="map-list" tabIndex={0} role="region" aria-label="Aircraft and weather near the airport, as lists">
        <table className="map-table">
          <caption>
            Aircraft within {area?.radius_nm ?? 25} nm
            {hidden > 0 && ` (${hidden} not shown: privacy or airport vehicles)`}
          </caption>
          <thead>
            <tr>
              <th scope="col">Callsign</th>
              <th scope="col">Type</th>
              <th scope="col">Altitude</th>
              <th scope="col">Speed</th>
              <th scope="col">Distance</th>
              <th scope="col">Position</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 ? (
              <tr>
                <td colSpan={6}>{status}</td>
              </tr>
            ) : (
              shown.map((a) => (
                <tr key={a.id}>
                  <th scope="row">{a.callsign ?? `${a.id.toUpperCase()} (no callsign)`}</th>
                  <td>{a.kind === "aircraft" ? "Aircraft" : "Unclassified target"}</td>
                  <td>{altitude(a)}</td>
                  <td>{a.ground_speed_kt === null ? "Unknown" : `${a.ground_speed_kt} kt`}</td>
                  <td>{a.distance_nm} nm</td>
                  <td>{secondsAgo(a.position_at, now)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        <table className="map-table">
          <caption>
            Observed weather at nearby airports (within {nearbyData?.area.radius_nm ?? 50} nm)
            {nearbyData && !nearbyData.complete && " (some stations may be missing)"}
          </caption>
          <thead>
            <tr>
              <th scope="col">Station</th>
              <th scope="col">Distance</th>
              <th scope="col">Conditions index</th>
              <th scope="col">Observed</th>
            </tr>
          </thead>
          <tbody>
            {stations.length === 0 ? (
              <tr>
                <td colSpan={4}>
                  {nearbyMessage}
                </td>
              </tr>
            ) : (
              stations.map((s) => (
                <tr key={s.station}>
                  <th scope="row">
                    {s.station}
                    {s.name && <span className="muted small"> {s.name}</span>}
                  </th>
                  <td>{s.distance_nm} nm</td>
                  <td>
                    {s.view === "stale" || s.conditions.score === null
                      ? s.view === "stale"
                        ? "Not scored (old report)"
                        : "Unknown"
                      : `${s.conditions.score} / 10 ${LEVEL_WORDS[s.conditions.level]}`}
                  </td>
                  <td>{formatUtcTime(s.observed_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <p className="disclaimer">
        {aircraftData?.disclaimer ??
          "Live positions from volunteer receiver networks. Coverage is incomplete and positions can be delayed; not for navigation or safety use."}
      </p>
    </section>
  );
}
