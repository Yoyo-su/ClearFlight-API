import "maplibre-gl/dist/maplibre-gl.css";

import type { Feature, FeatureCollection } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
// MapLibre finds its worker next to its own module, which bundling breaks;
// let Vite emit the (self-contained) worker and tell MapLibre where it is.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef } from "react";

import type { AircraftPosition } from "../api/types";
import type { StationView } from "../lib/ageing";
import { LEVEL_WORDS } from "./ConditionsCard";

// The map canvas (CF-010 §2-§5), loaded lazily by AirportMap. All data lives
// in React state; this component only draws it. Station and airport markers
// are DOM elements (readable text, no glyph downloads); aircraft are a symbol
// layer with a locally drawn plane icon.

maplibregl.setWorkerUrl(workerUrl);

export const MAP_STYLE_URL: string =
  import.meta.env.VITE_MAP_STYLE_URL ?? "https://tiles.openfreemap.org/styles/positron";

export interface MapViewProps {
  center: { latitude: number; longitude: number };
  radiusNm: number;
  aircraft: AircraftPosition[];
  stations: StationView[];
  airportLabel: string | null; // e.g. "EGLL · 8 Severe (observed)"
  radarTileUrl: string | null;
  onSelectAircraft: (id: string) => void;
  onSelectStation: (station: string) => void;
  onError: () => void;
}

const NM_PER_DEGREE = 60;

function circle(lat: number, lon: number, radiusNm: number, steps = 64): Feature {
  const coordinates = Array.from({ length: steps + 1 }, (_, i) => {
    const angle = (i / steps) * 2 * Math.PI;
    const dLat = (radiusNm / NM_PER_DEGREE) * Math.cos(angle);
    const dLon = ((radiusNm / NM_PER_DEGREE) * Math.sin(angle)) / Math.max(Math.cos((lat * Math.PI) / 180), 0.01);
    return [lon + dLon, lat + dLat];
  });
  return { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [coordinates] } };
}

function aircraftCollection(aircraft: AircraftPosition[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: aircraft.map((a) => ({
      type: "Feature",
      properties: {
        id: a.id,
        track: a.track_deg ?? 0,
        state: a.kind === "unclassified" ? "unclassified" : a.on_ground ? "ground" : "air",
      },
      geometry: { type: "Point", coordinates: [a.longitude, a.latitude] },
    })),
  };
}

/**
 * A plane silhouette as an SDF icon (tinted by the layer): filled when
 * airborne, outlined on the ground, dashed outline when unclassified (the
 * target may not be an aircraft) — shape, not only colour, tells them apart.
 */
function planeIcon(style: "filled" | "outline" | "dashed", size = 64): ImageData | null {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const s = size / 32;
  ctx.fillStyle = "#000";
  ctx.beginPath();
  // Nose up: fuselage, wings, tail.
  ctx.moveTo(16 * s, 2 * s);
  ctx.lineTo(18 * s, 12 * s);
  ctx.lineTo(29 * s, 18 * s);
  ctx.lineTo(29 * s, 20 * s);
  ctx.lineTo(18 * s, 17 * s);
  ctx.lineTo(17.5 * s, 25 * s);
  ctx.lineTo(21 * s, 28 * s);
  ctx.lineTo(21 * s, 30 * s);
  ctx.lineTo(16 * s, 28.5 * s);
  ctx.lineTo(11 * s, 30 * s);
  ctx.lineTo(11 * s, 28 * s);
  ctx.lineTo(14.5 * s, 25 * s);
  ctx.lineTo(14 * s, 17 * s);
  ctx.lineTo(3 * s, 20 * s);
  ctx.lineTo(3 * s, 18 * s);
  ctx.lineTo(14 * s, 12 * s);
  ctx.closePath();
  if (style === "filled") ctx.fill();
  else {
    ctx.lineWidth = 3 * s; // thick enough to survive SDF rendering
    ctx.lineJoin = "round";
    ctx.setLineDash(style === "dashed" ? [4 * s, 3 * s] : []);
    ctx.stroke();
  }
  return ctx.getImageData(0, 0, size, size);
}

export default function MapView({
  center,
  radiusNm,
  aircraft,
  stations,
  airportLabel,
  radarTileUrl,
  onSelectAircraft,
  onSelectStation,
  onError,
}: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const drawnRef = useRef("");
  const latest = useRef({ aircraft, stations, airportLabel, radarTileUrl, onSelectAircraft, onSelectStation, onError });
  latest.current = { aircraft, stations, airportLabel, radarTileUrl, onSelectAircraft, onSelectStation, onError };

  // Create the map once per airport.
  useEffect(() => {
    if (!container.current) return;
    let map: MapLibreMap;
    try {
      map = new maplibregl.Map({
        container: container.current,
        style: MAP_STYLE_URL,
        center: [center.longitude, center.latitude],
        zoom: 8,
        attributionControl: { compact: false },
        cooperativeGestures: true, // scrolling the page doesn't zoom the map
      });
    } catch {
      latest.current.onError(); // e.g. no WebGL
      return;
    }
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("error", (event) => {
      // Only a failure not tied to a tile or source, before the first load
      // (the style, WebGL), is fatal. A failed tile, at any time (a blip, or
      // a radar tile), just leaves that tile blank.
      const e = event as { sourceId?: string; tile?: unknown; error?: unknown };
      if (!readyRef.current && !e.sourceId && !e.tile) latest.current.onError();
      else console.warn("Map tile error", e.error);
    });
    map.on("load", () => {
      const dLat = radiusNm / NM_PER_DEGREE;
      const dLon = dLat / Math.max(Math.cos((center.latitude * Math.PI) / 180), 0.01);
      map.fitBounds(
        [
          [center.longitude - dLon, center.latitude - dLat],
          [center.longitude + dLon, center.latitude + dLat],
        ],
        { padding: 16, animate: false },
      );
      map.addSource("area", { type: "geojson", data: circle(center.latitude, center.longitude, radiusNm) });
      map.addLayer({ id: "area", type: "line", source: "area", paint: { "line-color": "#1f5fbf", "line-opacity": 0.35, "line-width": 1.5 } });
      for (const [name, style] of [
        ["plane-air", "filled"],
        ["plane-ground", "outline"],
        ["plane-unclassified", "dashed"],
      ] as const) {
        const icon = planeIcon(style);
        if (icon) map.addImage(name, icon, { sdf: true, pixelRatio: 2 }); // drawn at 2x for crisp edges
      }
      map.addSource("aircraft", { type: "geojson", data: aircraftCollection([]) });
      map.addLayer({
        id: "aircraft",
        type: "symbol",
        source: "aircraft",
        layout: {
          "icon-image": ["match", ["get", "state"], "air", "plane-air", "ground", "plane-ground", "plane-unclassified"],
          "icon-size": ["match", ["get", "state"], "ground", 0.55, 0.75],
          "icon-rotate": ["get", "track"],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
        },
        paint: {
          "icon-color": ["match", ["get", "state"], "air", "#13213a", "ground", "#4a5872", "#8c99ad"],
          "icon-halo-color": "#ffffff",
          "icon-halo-width": 1.5,
        },
      });
      map.on("click", "aircraft", (event) => {
        const id = event.features?.[0]?.properties?.id;
        if (typeof id === "string") latest.current.onSelectAircraft(id);
      });
      map.on("mouseenter", "aircraft", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "aircraft", () => (map.getCanvas().style.cursor = ""));
      readyRef.current = true;
      drawnRef.current = "";
      draw();
    });
    return () => {
      readyRef.current = false;
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
    // The map is per airport; data changes are drawn by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center.latitude, center.longitude, radiusNm]);

  function draw() {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const data = latest.current;
    // Redraw only when something visible changed (the parent re-renders on
    // every clock tick).
    const key = JSON.stringify([
      data.aircraft.map((a) => [a.id, a.latitude, a.longitude, a.track_deg, a.on_ground, a.kind]),
      data.stations.map((st) => [st.station, st.view, st.conditions.score]),
      data.airportLabel,
      data.radarTileUrl,
    ]);
    if (key === drawnRef.current) return;
    drawnRef.current = key;
    (map.getSource("aircraft") as GeoJSONSource | undefined)?.setData(aircraftCollection(data.aircraft));

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    const label = (text: string, className: string, lon: number, lat: number, station?: string, above = false) => {
      const el = document.createElement("div");
      el.className = className;
      el.textContent = text;
      el.setAttribute("aria-hidden", "true"); // the list below carries the same data
      if (station) {
        el.style.cursor = "pointer";
        el.addEventListener("click", () => latest.current.onSelectStation(station));
      }
      // The airport label sits above its point, so it doesn't cover the field.
      const options = above ? { element: el, anchor: "bottom" as const, offset: [0, -18] as [number, number] } : { element: el };
      markersRef.current.push(new maplibregl.Marker(options).setLngLat([lon, lat]).addTo(map));
    };
    if (data.airportLabel) label(data.airportLabel, "map-label map-label-airport", center.longitude, center.latitude, undefined, true);
    for (const s of data.stations) {
      const score =
        s.view === "stale" ? "old report" : s.conditions.score === null ? "unknown" : `${s.conditions.score} ${LEVEL_WORDS[s.conditions.level]}`;
      label(`${s.station} · ${score}`, `map-label map-label-${s.view === "stale" ? "stale" : s.conditions.level}`, s.longitude, s.latitude, s.station);
    }

    const radar = map.getSource("radar");
    if (data.radarTileUrl && !radar) {
      map.addSource("radar", { type: "raster", tiles: [data.radarTileUrl], tileSize: 256, maxzoom: 7 });
      map.addLayer({ id: "radar", type: "raster", source: "radar", paint: { "raster-opacity": 0.6 } }, "area");
    } else if (!data.radarTileUrl && radar) {
      map.removeLayer("radar");
      map.removeSource("radar");
    } else if (data.radarTileUrl && radar && (radar as maplibregl.RasterTileSource).tiles?.[0] !== data.radarTileUrl) {
      (radar as maplibregl.RasterTileSource).setTiles([data.radarTileUrl]);
    }
  }

  // Redraw whenever the data changes.
  useEffect(draw, [aircraft, stations, airportLabel, radarTileUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={container} className="map-canvas" role="region" aria-label="Map of the area (the list below has the same information)" />;
}
