import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { fixture, fixtureFetch, type Fixture } from "./helpers";

// The live map section (CF-010 design r3). MapLibre is replaced by a stub that
// shows what it was given; the on-screen observer is controlled by the test.

vi.mock("../../src/components/MapView", () => ({
  default: (props: { aircraft: unknown[]; stations: unknown[]; radarTileUrl: string | null; airportLabel: string | null; onError: () => void }) => (
    <div data-testid="map-view">
      <span data-testid="map-aircraft">{props.aircraft.length}</span>
      <span data-testid="map-stations">{props.stations.length}</span>
      <span data-testid="map-radar">{props.radarTileUrl ?? "none"}</span>
      <span data-testid="map-airport">{props.airportLabel}</span>
      <button type="button" onClick={props.onError}>
        break the map
      </button>
    </div>
  ),
}));

const NOW = new Date("2026-10-30T07:55:00Z"); // the fixtures' fetch time

let observers: { callback: IntersectionObserverCallback; element: Element | null }[] = [];
class FakeObserver {
  constructor(public callback: IntersectionObserverCallback) {
    observers.push(this as unknown as { callback: IntersectionObserverCallback; element: Element | null });
  }
  element: Element | null = null;
  observe(element: Element) {
    this.element = element;
  }
  disconnect() {}
  unobserve() {}
  takeRecords() {
    return [];
  }
}

async function setOnScreen(onScreen: boolean) {
  await act(async () => {
    for (const o of observers) {
      o.callback([{ isIntersecting: onScreen, target: o.element } as IntersectionObserverEntry], o as unknown as IntersectionObserver);
    }
  });
}

async function settle(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

type Route = Fixture | "network";
let layers: { aircraft: () => Route; nearby: () => Route; radar: () => Route };

let conditionsFixture = "conditions-egll-severe";

function makeFetch() {
  return fixtureFetch((url) => {
    if (url.includes("/aircraft")) return layers.aircraft();
    if (url.includes("/nearby-conditions")) return layers.nearby();
    if (url.includes("/map/radar")) return layers.radar();
    if (url.includes("/forecast")) return fixture("forecast-egll-fog");
    return fixture(conditionsFixture);
  });
}

function calls(fetch: ReturnType<typeof makeFetch>, part: string) {
  return fetch.mock.calls.filter((call) => String(call[0]).includes(part)).length;
}

async function renderMap() {
  const fetch = makeFetch();
  vi.stubGlobal("fetch", fetch);
  render(
    <MemoryRouter initialEntries={["/airport/EGLL"]}>
      <App />
    </MemoryRouter>,
  );
  await settle();
  return fetch;
}

function section() {
  return screen.getByRole("region", { name: "Live map" });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
  vi.setSystemTime(NOW);
  setVisibility("visible");
  observers = [];
  vi.stubGlobal("IntersectionObserver", FakeObserver);
  conditionsFixture = "conditions-egll-severe";
  layers = {
    aircraft: () => fixture("aircraft-egll-available"),
    nearby: () => fixture("nearby-egll-available"),
    radar: () => fixture("radar-disabled"),
  };
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("live map: requests only while on screen and visible (M5)", () => {
  it("requests nothing until the section is near the viewport", async () => {
    const fetch = await renderMap();
    expect(calls(fetch, "/aircraft")).toBe(0);
    expect(within(section()).getAllByText("The map loads when you scroll to it.").length).toBeGreaterThan(0);
    await setOnScreen(true);
    await settle();
    expect([calls(fetch, "/aircraft"), calls(fetch, "/nearby-conditions"), calls(fetch, "/map/radar")]).toEqual([1, 1, 1]);
    expect(screen.getByTestId("map-aircraft")).toHaveTextContent(/\d+/);
  });

  it("refreshes aircraft every 30 s on screen, and stops off screen or in a hidden tab", async () => {
    const fetch = await renderMap();
    await setOnScreen(true);
    await settle();
    await settle(30_000);
    expect(calls(fetch, "/aircraft")).toBe(2);
    await setOnScreen(false);
    await settle(90_000);
    expect(calls(fetch, "/aircraft")).toBe(2);
    await setOnScreen(true);
    await settle();
    expect(calls(fetch, "/aircraft")).toBe(3); // resumed: the data was old
    setVisibility("hidden");
    await settle(90_000);
    expect(calls(fetch, "/aircraft")).toBe(3);
  });

  it("defers a 503 retry while the tab is hidden, and runs it on return", async () => {
    const replies: Route[] = [fixture("error-503-busy"), fixture("aircraft-egll-available")];
    layers.aircraft = () => replies.shift() ?? fixture("aircraft-egll-available");
    const fetch = await renderMap();
    await setOnScreen(true);
    await settle();
    expect(calls(fetch, "/aircraft")).toBe(1);
    setVisibility("hidden");
    await settle(20_000); // the Retry-After (13 s) passes while hidden
    expect(calls(fetch, "/aircraft")).toBe(1);
    setVisibility("visible");
    await settle();
    expect(calls(fetch, "/aircraft")).toBe(2);
  });
});

describe("live map: what's shown, and for how long", () => {
  it("drops each aircraft at its expiry, and says so when refreshes fail", async () => {
    const replies: Route[] = [fixture("aircraft-egll-available")];
    layers.aircraft = () => replies.shift() ?? "network";
    await renderMap();
    await setOnScreen(true);
    await settle();
    const before = Number(screen.getByTestId("map-aircraft").textContent);
    expect(before).toBeGreaterThan(0);
    await settle(70_000); // every position (at most 60 s old) has expired
    expect(screen.getByTestId("map-aircraft")).toHaveTextContent("0");
    expect(within(section()).getAllByText("Live positions couldn't be updated.").length).toBeGreaterThan(0);
  });

  it("withdraws a 'no aircraft' claim after 60 s without a fresh answer", async () => {
    const replies: Route[] = [fixture("aircraft-rjbb-no-aircraft")];
    layers.aircraft = () => replies.shift() ?? "network";
    await renderMap();
    await setOnScreen(true);
    await settle();
    expect(within(section()).getAllByText("No aircraft reported within 25 nm.").length).toBeGreaterThan(0);
    await settle(61_000);
    expect(within(section()).queryByText("No aircraft reported within 25 nm.")).not.toBeInTheDocument();
    expect(within(section()).getAllByText("Live positions couldn't be updated.").length).toBeGreaterThan(0);
  });

  it.each([
    ["aircraft-rjbb-coverage-unknown", "Can't confirm traffic near this airport: receivers haven't reported traffic here recently."],
    ["aircraft-egll-quota", "Live positions limit reached; try again after 00:00 UTC."],
    ["aircraft-egll-disabled", "Live positions aren't available."],
  ])("explains %s", async (name, text) => {
    layers.aircraft = () => fixture(name);
    await renderMap();
    await setOnScreen(true);
    await settle();
    expect(within(section()).getAllByText(text).length).toBeGreaterThan(0);
  });

  it("lists the same aircraft and stations for keyboard and screen-reader users (M6)", async () => {
    layers.aircraft = () => fixture("aircraft-kjfk-available");
    await renderMap();
    await setOnScreen(true);
    await settle();
    const aircraftTable = screen.getByRole("table", { name: /Aircraft within 25 nm \(7 not shown/ });
    expect(within(aircraftTable).getAllByRole("row").length - 1).toBe(Number(screen.getByTestId("map-aircraft").textContent));
    const weather = screen.getByRole("table", { name: /Observed weather at nearby airports/ });
    expect(within(weather).getByText("EGWU")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip the map, go to the list" })).toHaveAttribute("href", "#map-list");
  });

  it("labels the airport's own marker with its observed index", async () => {
    await renderMap();
    await setOnScreen(true);
    await settle();
    expect(screen.getByTestId("map-airport")).toHaveTextContent("EGLL · 8 Severe (observed)");
  });

  it("keeps the list working when the map can't load", async () => {
    await renderMap();
    await setOnScreen(true);
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "break the map" }));
    expect(within(section()).getByText(/The map couldn't load/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Aircraft within/ })).toBeInTheDocument();
  });
});

describe("live map: radar (M4)", () => {
  it("shows no radar control when the radar is disabled", async () => {
    await renderMap();
    await setOnScreen(true);
    await settle();
    expect(screen.queryByRole("checkbox", { name: /Radar/ })).not.toBeInTheDocument();
    expect(screen.getByTestId("map-radar")).toHaveTextContent("none");
  });

  it("is off until the visitor turns it on, then hides the frame once it's stale", async () => {
    layers.radar = () => fixture("radar-available");
    await renderMap();
    await setOnScreen(true);
    await settle();
    const toggle = screen.getByRole("checkbox", { name: /Radar \(observed\)/ });
    expect(toggle).not.toBeChecked();
    expect(screen.getByTestId("map-radar")).toHaveTextContent("none"); // nothing from RainViewer yet
    fireEvent.click(toggle);
    expect(screen.getByTestId("map-radar")).toHaveTextContent("https://tilecache.rainviewer.com/v2/radar/fixture0/256/{z}/{x}/{y}/2/1_0.png");
    expect(within(section()).getByText(/coarse at this zoom/)).toBeInTheDocument();
    layers.radar = () => "network";
    await settle(16 * 60_000); // past the frame's current_until (08:10)
    expect(screen.getByTestId("map-radar")).toHaveTextContent("none");
    expect(within(section()).getByText(/radar unavailable/)).toBeInTheDocument();
  });

  it("shows nothing from an invalid radar index", async () => {
    layers.radar = () => fixture("radar-invalid-index");
    await renderMap();
    await setOnScreen(true);
    await settle();
    fireEvent.click(screen.getByRole("checkbox", { name: /Radar/ }));
    expect(screen.getByTestId("map-radar")).toHaveTextContent("none");
  });
});

describe("live map: review round 1 fixes (CF-010)", () => {
  it("keeps the map mounted after scrolling away (no re-download)", async () => {
    await renderMap();
    await setOnScreen(true);
    await settle();
    expect(screen.getByTestId("map-view")).toBeInTheDocument();
    await setOnScreen(false);
    await settle();
    expect(screen.getByTestId("map-view")).toBeInTheDocument();
  });

  it("announces state changes only, not the ticking update age", async () => {
    await renderMap();
    await setOnScreen(true);
    await settle(10_000);
    const live = within(section()).getAllByRole("status");
    expect(live.some((el) => /updated/.test(el.textContent ?? ""))).toBe(false);
    expect(within(section()).getByText(/updated \d+ s ago/)).toBeInTheDocument();
  });

  it("never scores the airport on the map from a report that is too old", async () => {
    conditionsFixture = "conditions-egll-too-old";
    await renderMap();
    await setOnScreen(true);
    await settle();
    expect(screen.getByTestId("map-airport")).toHaveTextContent(/^EGLL · old report$/); // no score, and why
  });

  it("removes each later aircraft exactly at its own expiry", async () => {
    const body = fixture("aircraft-kjfk-available").body as { aircraft: { expires_at: string }[] };
    const expiries = [...new Set(body.aircraft.map((a) => Date.parse(a.expires_at)))].sort((x, y) => x - y);
    const second = expiries[1]!;
    const replies: Route[] = [fixture("aircraft-kjfk-available")];
    layers.aircraft = () => replies.shift() ?? "network";
    await renderMap();
    await setOnScreen(true);
    await settle();
    await settle(second - Date.now() + 1); // just past the second-earliest expiry
    const left = body.aircraft.filter((a) => Date.parse(a.expires_at) > Date.now()).length;
    expect(screen.getByTestId("map-aircraft")).toHaveTextContent(String(left));
  });

  it("says nearby reports are out of date, not that there are no stations", async () => {
    const replies: Route[] = [fixture("nearby-egll-available")];
    layers.nearby = () => replies.shift() ?? "network";
    await renderMap();
    await setOnScreen(true);
    await settle();
    await settle(4 * 60 * 60_000); // every report is past its stale_until
    const weather = screen.getByRole("table", { name: /Observed weather at nearby airports/ });
    expect(within(weather).getByText("Nearby reports are out of date.")).toBeInTheDocument();
    expect(within(weather).queryByText("No nearby reporting stations.")).not.toBeInTheDocument();
  });

  it("refreshes nearby weather too with Refresh map", async () => {
    const fetch = await renderMap();
    await setOnScreen(true);
    await settle(31_000);
    const before = calls(fetch, "/nearby-conditions");
    fireEvent.click(screen.getByRole("button", { name: "Refresh map" }));
    await settle();
    expect(calls(fetch, "/nearby-conditions")).toBe(before + 1);
  });

  it("names RainViewer in the privacy note when radar tiles load", async () => {
    layers.radar = () => fixture("radar-available");
    await renderMap();
    await setOnScreen(true);
    await settle();
    expect(within(section()).queryByText(/radar tiles from RainViewer/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Radar/ }));
    expect(within(section()).getByText(/radar tiles from RainViewer/)).toBeInTheDocument();
    expect(within(section()).getByRole("link", { name: "Radar © RainViewer" })).toHaveAttribute("href", "https://www.rainviewer.com");
  });
});

describe("live map: review round 2 fixes (CF-010)", () => {
  it("says in text whether each target is an aircraft or unclassified", async () => {
    layers.aircraft = () => fixture("aircraft-kjfk-available");
    await renderMap();
    await setOnScreen(true);
    await settle();
    const table = screen.getByRole("table", { name: /Aircraft within 25 nm/ });
    expect(within(table).getByRole("columnheader", { name: "Type" })).toBeInTheDocument();
    expect(within(table).getAllByText("Aircraft").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("Unclassified target").length).toBeGreaterThan(0);
  });

  it("refreshes nearby weather on every permitted Refresh map click", async () => {
    const fetch = await renderMap();
    await setOnScreen(true);
    await settle(31_000);
    const button = screen.getByRole("button", { name: "Refresh map" });
    fireEvent.click(button);
    await settle(31_000); // past the 30 s cooldown, before the 60 s default
    const before = calls(fetch, "/nearby-conditions");
    fireEvent.click(button);
    await settle();
    expect(calls(fetch, "/nearby-conditions")).toBe(before + 1);
  });
});
