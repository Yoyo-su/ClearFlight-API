import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import { rememberAirport } from "../../src/lib/recent";
import { controlledFetch, fixture, fixtureFetch, response, type Fixture } from "./helpers";

const NOW = new Date("2026-10-30T07:55:00Z"); // the fixtures' fetch time

let navigateTo: (path: string) => void = () => {};
function Probe() {
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    navigateTo = navigate;
  }, [navigate]);
  return <output data-testid="path">{location.pathname}</output>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Probe />
    </MemoryRouter>,
  );
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

// The page also loads the forecast (CF-008). Tests that count or script
// conditions requests see only those; forecast requests go to `forecastFetch`.
const FORECASTS: Record<string, string> = { EGLL: "forecast-egll-fog", LHR: "forecast-egll-fog", KJFK: "forecast-kjfk-low", JFK: "forecast-kjfk-low" };
let forecastFetch = fixtureFetch(() => "network");
function defaultForecasts() {
  return fixtureFetch((url) => {
    const code = decodeURIComponent(/airports\/([^/]+)\/forecast/.exec(url)?.[1] ?? "");
    return fixture(FORECASTS[code.toUpperCase()] ?? "forecast-rjbb-no-forecast");
  });
}
function stubFetch(conditions: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
    String(input).includes("/forecast") ? forecastFetch(input, init) : conditions(input, init),
  );
}

function routeByCode(map: Record<string, Fixture | "network">) {
  return fixtureFetch((url) => {
    const match = /airports\/([^/]+)\/conditions/.exec(url);
    const result = match ? map[decodeURIComponent(match[1]!)] : undefined;
    if (!result) throw new Error(`unexpected fetch ${url}`);
    return result;
  });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: false });
  vi.setSystemTime(NOW);
  setVisibility("visible");
  forecastFetch = defaultForecasts();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("airport page: current data", () => {
  it("shows the airport, clocks, status, score, factors and observation", async () => {
    stubFetch(routeByCode({ EGLL: fixture("conditions-egll-severe") }));
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByRole("heading", { level: 1, name: "London Heathrow Airport" })).toBeInTheDocument();
    expect(screen.getByText("London, United Kingdom")).toBeInTheDocument();
    expect(screen.getByText("Observed 35 min ago · 07:20 UTC")).toBeInTheDocument();
    expect(screen.getByText("Fri 30 Oct · GMT (UTC+0)")).toBeInTheDocument();
    const index = screen.getByRole("region", { name: "Experimental conditions index" });
    expect(within(index).getByText("8")).toBeInTheDocument();
    expect(within(index).getByText("Severe")).toBeInTheDocument();
    expect(within(index).getByText(/mainly from visibility of 1.3 km/)).toBeInTheDocument();
    expect(within(index).getAllByRole("listitem")).toHaveLength(4);
    expect(within(index).getByText(/does not predict delays, cancellations or flight safety/)).toBeInTheDocument();
    const observed = screen.getByRole("region", { name: "Observed weather" });
    expect(within(observed).getByText("1.3 km (0.8 mi)")).toBeInTheDocument();
    expect(within(observed).getByText("Overcast at 200 ft")).toBeInTheDocument();
    expect(within(observed).getByText("Mist (BR)")).toBeInTheDocument();
    expect(within(observed).getByText(/METAR EGLL 300720Z/)).toBeInTheDocument();
    expect(screen.getByText("Observed 07:20 UTC · Fetched 07:55 UTC")).toBeInTheDocument();
    expect(document.title).toBe("London Heathrow Airport (EGLL) – ClearFlight");
  });

  it("rewrites the URL to the canonical code without fetching again (D8)", async () => {
    const fetch = routeByCode({ LHR: fixture("conditions-egll-severe") });
    stubFetch(fetch);
    renderAt("/airport/lhr");
    await settle();
    expect(screen.getByTestId("path")).toHaveTextContent("/airport/EGLL");
    await settle(1000);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByText("London Heathrow Airport")).toBeInTheDocument();
  });

  it("keeps an IATA-only airport's code as canonical", async () => {
    stubFetch(routeByCode({ AAI: fixture("conditions-aai-no-station") }));
    renderAt("/airport/aai");
    await settle();
    expect(screen.getByTestId("path")).toHaveTextContent("/airport/AAI");
    expect(screen.getByRole("heading", { name: "No weather station" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Refresh|Try again/ })).not.toBeInTheDocument();
  });

  it("remembers the airport as recently viewed", async () => {
    stubFetch(routeByCode({ EGLL: fixture("conditions-egll-severe") }));
    renderAt("/airport/EGLL");
    await settle();
    expect(JSON.parse(window.localStorage.getItem("clearflight.recentAirports")!)).toEqual([
      { code: "EGLL", iata: "LHR", name: "London Heathrow Airport" },
    ]);
  });

  it("shows 'Unknown' with the reason when a factor is missing", async () => {
    stubFetch(routeByCode({ EGLL: fixture("conditions-egll-unknown") }));
    renderAt("/airport/EGLL");
    await settle();
    const index = screen.getByRole("region", { name: "Experimental conditions index" });
    expect(within(index).getAllByText("Unknown").length).toBeGreaterThan(1);
    expect(within(index).getByText("No score: the visibility wasn't reported.")).toBeInTheDocument();
    expect(within(index).queryByText("/ 10")).not.toBeInTheDocument();
  });

  it("scores dense fog with an obscured sky", async () => {
    stubFetch(routeByCode({ EGKK: fixture("conditions-egkk-fog") }));
    renderAt("/airport/EGKK");
    await settle();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("Sky obscured; height not reported")).toBeInTheDocument();
  });

  it("shows a stale report unscored, with its age", async () => {
    stubFetch(routeByCode({ EGLL: fixture("conditions-egll-stale") }));
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByText(/This report is 2 h 5 min old/)).toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText("Not scored: this report is too old to score.")).toBeInTheDocument();
  });
});

describe("airport page: unavailable data and errors", () => {
  it.each([
    ["conditions-rjbb-no-report", "RJBB", "No current weather report", /hasn’t published a report recently/, "Refresh"],
    ["conditions-egll-too-old", "EGLL", "No current weather report", /\(03:50 UTC, 4 h 5 min ago\) is too old to show/, "Refresh"],
    ["error-502-provider", "EGLL", "The weather service didn’t respond", /usually temporary/, "Try again"],
    ["error-504-timeout", "EGLL", "The weather service didn’t respond", /usually temporary/, "Try again"],
  ])("%s", async (name, code, title, body, button) => {
    stubFetch(routeByCode({ [code]: fixture(name) }));
    renderAt(`/airport/${code}`);
    await settle();
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByText(body)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: button })).toBeEnabled();
  });

  it("explains an invalid code and offers search", async () => {
    stubFetch(routeByCode({ XX: fixture("error-400-invalid-code") }));
    renderAt("/airport/xx");
    await settle();
    expect(screen.getByText(/“XX” isn’t an airport code/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "XX" })).toBeInTheDocument();
    const search = screen.getAllByRole("search").at(-1)!;
    expect(within(search).getByLabelText("Airport name, city or code")).toHaveAttribute("name", "q");
    expect(screen.getByTestId("path")).toHaveTextContent("/airport/xx");
  });

  it("explains an unknown airport", async () => {
    stubFetch(routeByCode({ ZZZ: fixture("error-404-not-found") }));
    renderAt("/airport/ZZZ");
    await settle();
    expect(screen.getByText("We couldn’t find an airport with the code ZZZ.")).toBeInTheDocument();
  });

  it("explains a network failure and retries on request", async () => {
    const fetch = routeByCode({ EGLL: "network" });
    stubFetch(fetch);
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByRole("heading", { name: "Can’t reach ClearFlight" })).toBeInTheDocument();
    stubFetch(routeByCode({ EGLL: fixture("conditions-egll-severe") }));
    await act(async () => screen.getByRole("button", { name: "Try again" }).click());
    await settle();
    expect(screen.getByText("London Heathrow Airport")).toBeInTheDocument();
  });

  it("counts down on 503, retries once automatically, then succeeds", async () => {
    const replies = [fixture("error-503-busy"), fixture("conditions-egll-severe")];
    const fetch = fixtureFetch(() => replies.shift()!);
    stubFetch(fetch);
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByText("Trying again automatically in 13 s…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeDisabled();
    await settle(5000);
    expect(screen.getByText("Trying again automatically in 8 s…")).toBeInTheDocument();
    await settle(8000);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(screen.getByText("London Heathrow Airport")).toBeInTheDocument();
  });

  it("enables Try again after the automatic retry also fails", async () => {
    stubFetch(routeByCode({ EGLL: fixture("error-503-busy") }));
    renderAt("/airport/EGLL");
    await settle(13000);
    await settle(1000);
    expect(screen.getByText("Please try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("says when loading is slow", async () => {
    const { fn } = controlledFetch();
    stubFetch(fn);
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByText("Loading weather…")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "EGLL" })).toBeInTheDocument();
    await settle(10000);
    expect(screen.getByText("Still waiting for the weather service…")).toBeInTheDocument();
  });
});

describe("airport page: refresh and ageing (D4, D11)", () => {
  it("refreshes every 5 minutes while visible, not while hidden", async () => {
    const fetch = routeByCode({ EGLL: fixture("conditions-egll-severe") });
    stubFetch(fetch);
    renderAt("/airport/EGLL");
    await settle();
    await settle(5 * 60 * 1000);
    expect(fetch).toHaveBeenCalledTimes(2);
    setVisibility("hidden");
    await settle(10 * 60 * 1000);
    expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => setVisibility("visible"));
    await settle();
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("limits manual refresh to once a minute", async () => {
    const fetch = routeByCode({ EGLL: fixture("conditions-egll-severe") });
    stubFetch(fetch);
    renderAt("/airport/EGLL");
    await settle();
    const button = screen.getByRole("button", { name: "Refresh" });
    await act(async () => button.click());
    await settle();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Checked just now")).toBeInTheDocument();
    expect(button).toBeDisabled();
    await act(async () => button.click());
    expect(fetch).toHaveBeenCalledTimes(2);
    await settle(60 * 1000);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });

  it("keeps the last good data when a refresh fails, and ages it", async () => {
    const replies: (Fixture | "network")[] = [fixture("conditions-egll-severe")];
    stubFetch(fixtureFetch(() => replies.shift() ?? "network"));
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByText("8")).toBeInTheDocument();

    await settle(5 * 60 * 1000); // refresh fails
    expect(screen.getByText(/Couldn’t update just now — showing the report from 07:20 UTC/)).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();

    await settle(50 * 60 * 1000 + 1000); // just past current_until (08:50)
    expect(screen.queryByText("8")).not.toBeInTheDocument();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
    expect(screen.getByText(/This report is 1 h 31 min old/)).toBeInTheDocument();

    await settle(90 * 60 * 1000); // just past stale_until (10:20)
    expect(screen.queryByRole("region", { name: "Observed weather" })).not.toBeInTheDocument();
    expect(screen.getByText(/The latest weather report \(07:20 UTC, 3 h 1 min ago\) is too old to show/)).toBeInTheDocument();
  });

  it("withdraws the score exactly at current_until, not at the next 15 s tick", async () => {
    vi.setSystemTime(new Date("2026-10-30T08:49:50Z")); // 10 s before current_until
    stubFetch(fixtureFetch(() => fixture("conditions-egll-severe")));
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByText("8")).toBeInTheDocument();
    await settle(10_002); // just past 08:50:00, well before the next 15 s tick
    expect(screen.getByText("Not scored")).toBeInTheDocument();
  });

  it("keeps the last good data when a refresh returns a malformed 200", async () => {
    const replies: (Fixture | "network")[] = [fixture("conditions-egll-severe")];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        const next = replies.shift();
        return next && next !== "network" ? response(next) : new Response("{not json", { status: 200 });
      }),
    );
    renderAt("/airport/EGLL");
    await settle();
    await settle(5 * 60 * 1000);
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText(/Couldn’t update just now/)).toBeInTheDocument();
  });

  it("applies ageing on return from a background tab", async () => {
    stubFetch(fixtureFetch(() => "network"));
    stubFetch(fixtureFetch(() => fixture("conditions-egll-severe")));
    renderAt("/airport/EGLL");
    await settle();
    stubFetch(fixtureFetch(() => "network"));
    setVisibility("hidden");
    vi.setSystemTime(new Date("2026-10-30T11:00:00Z"));
    await act(async () => setVisibility("visible"));
    await settle();
    expect(screen.getByText(/is too old to show/)).toBeInTheDocument();
  });
});

describe("airport page: request ownership", () => {
  it("ignores a late response for the previous airport", async () => {
    const { fn, pending } = controlledFetch();
    stubFetch(fn);
    renderAt("/airport/EGLL");
    await settle();
    await act(async () => navigateTo("/airport/KJFK"));
    await settle();
    expect(pending.map((p) => p.url)).toEqual([
      "/v1/airports/EGLL/conditions",
      "/v1/airports/KJFK/conditions",
    ]);
    expect(pending[0]!.signal?.aborted).toBe(true);
    await act(async () => pending[1]!.resolve(response(fixture("conditions-kjfk-low"))));
    await act(async () => pending[0]!.resolve(response(fixture("conditions-egll-severe"))));
    await settle();
    expect(screen.getByText("John F. Kennedy International Airport")).toBeInTheDocument();
    expect(screen.queryByText("London Heathrow Airport")).not.toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent("/airport/KJFK");
  });

  it("applies only the newest of overlapping refreshes", async () => {
    const { fn, pending } = controlledFetch();
    stubFetch(fn);
    renderAt("/airport/EGLL");
    await settle();
    await act(async () => pending[0]!.resolve(response(fixture("conditions-egll-severe"))));
    await settle(5 * 60 * 1000); // auto refresh 1
    await act(async () => screen.getByRole("button", { name: "Refresh" }).click()); // refresh 2
    await settle();
    expect(pending).toHaveLength(3);
    expect(pending[1]!.signal?.aborted).toBe(true);
    await act(async () => pending[2]!.resolve(response(fixture("conditions-egll-stale"))));
    await act(async () => pending[1]!.resolve(response(fixture("conditions-egll-severe"))));
    await settle();
    expect(screen.getByText("Not scored")).toBeInTheDocument();
  });

  it("ignores a late response even if it ignores cancellation", async () => {
    const pending: { url: string; resolve: (r: Response) => void }[] = [];
    // This fetch never rejects on abort, so only the ownership guard can stop it.
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => new Promise<Response>((resolve) => pending.push({ url: String(input), resolve }))),
    );
    renderAt("/airport/EGLL");
    await settle();
    await act(async () => navigateTo("/airport/KJFK"));
    await settle();
    const egll = pending.find((p) => p.url.includes("EGLL"))!;
    const kjfk = pending.find((p) => p.url.includes("KJFK"))!;
    await act(async () => kjfk.resolve(response(fixture("conditions-kjfk-low"))));
    await act(async () => egll.resolve(response(fixture("conditions-egll-severe"))));
    await settle();
    expect(screen.getByText("John F. Kennedy International Airport")).toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent("/airport/KJFK");
  });

  it("cancels a pending 503 retry when a newer refresh succeeds", async () => {
    const replies: Fixture[] = [
      fixture("conditions-egll-severe"),
      fixture("error-503-busy"), // auto refresh at 5 min: schedules a retry in 13 s
      fixture("conditions-egll-severe"), // manual refresh at +3 s succeeds
    ];
    const fetch = fixtureFetch(() => replies.shift() ?? fixture("error-503-busy"));
    stubFetch(fetch);
    renderAt("/airport/EGLL");
    await settle();
    await settle(5 * 60 * 1000);
    expect(screen.getByText(/Couldn’t update just now/)).toBeInTheDocument();
    await settle(3000);
    await act(async () => screen.getByRole("button", { name: "Refresh" }).click());
    await settle();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(screen.queryByText(/Couldn’t update just now/)).not.toBeInTheDocument();
    await settle(20_000); // past the old retry time
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(screen.queryByText(/Couldn’t update just now/)).not.toBeInTheDocument();
  });

  it("cancels a 503 retry when leaving the airport", async () => {
    const fetch = routeByCode({ EGLL: fixture("error-503-busy"), KJFK: fixture("conditions-kjfk-low") });
    stubFetch(fetch);
    renderAt("/airport/EGLL");
    await settle();
    await act(async () => navigateTo("/airport/KJFK"));
    await settle(20000);
    const urls = fetch.mock.calls.map((call) => String(call[0]));
    expect(urls.filter((url) => url.includes("EGLL"))).toHaveLength(1);
    expect(screen.getByText("John F. Kennedy International Airport")).toBeInTheDocument();
  });
});

describe("home page and search (D3, D5)", () => {
  function searchFetch(map: Record<string, Fixture | "network">) {
    return fixtureFetch((url) => {
      const query = new URL(url, "http://x").searchParams.get("q") ?? "";
      const result = map[query];
      if (!result) throw new Error(`unexpected search ${query}`);
      return result;
    });
  }

  it("shows the hint and pilot shortcuts before typing", () => {
    stubFetch(searchFetch({}));
    renderAt("/");
    expect(screen.getByLabelText("Airport name, city or code")).toBeInTheDocument();
    expect(screen.getByText("Type at least 2 characters.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "London Heathrow · LHR" })).toHaveAttribute("href", "/airport/EGLL");
    expect(screen.queryByText("Recently viewed")).not.toBeInTheDocument();
  });

  it("searches as you type after a pause and lists results as links", async () => {
    const fetch = searchFetch({ lon: fixture("search-lon") });
    stubFetch(fetch);
    renderAt("/");
    fireEvent.change(screen.getByLabelText("Airport name, city or code"), { target: { value: "lon" } });
    expect(screen.getByText("Searching…")).toBeInTheDocument();
    await settle(200);
    expect(fetch).not.toHaveBeenCalled();
    await settle(50);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/airports found/)).toBeInTheDocument();
    const results = screen.getByRole("list", { name: "Search results" });
    expect(within(results).getByRole("link", { name: /London Heathrow Airport/ })).toHaveAttribute(
      "href",
      "/airport/EGLL",
    );
  });

  it("opens the first result on Enter", async () => {
    stubFetch(searchFetch({ osaka: fixture("search-osaka") }));
    renderAt("/?q=osaka");
    await settle(250);
    stubFetch(routeByCode({ RJBB: fixture("conditions-rjbb-moderate") }));
    fireEvent.submit(screen.getByRole("search"));
    await settle();
    expect(screen.getByTestId("path")).toHaveTextContent("/airport/RJBB");
  });

  it("explains no results", async () => {
    stubFetch(searchFetch({ zzqq: fixture("search-none") }));
    renderAt("/?q=zzqq");
    await settle(250);
    expect(screen.getByText(/No airports match “zzqq”/)).toBeInTheDocument();
    expect(screen.getByText("Try one of our pilot airports")).toBeInTheDocument();
  });

  it("offers Retry when search fails", async () => {
    stubFetch(searchFetch({ lon: "network" }));
    renderAt("/?q=lon");
    await settle(250);
    expect(screen.getByText("Search isn’t available right now.")).toBeInTheDocument();
    stubFetch(searchFetch({ lon: fixture("search-lon") }));
    await act(async () => screen.getByRole("button", { name: "Retry" }).click());
    await settle(250);
    expect(screen.getByText(/airports found/)).toBeInTheDocument();
  });

  it("treats a server error as unavailable search", async () => {
    stubFetch(searchFetch({ lon: fixture("error-502-provider") }));
    renderAt("/?q=lon");
    await settle(250);
    expect(screen.getByText("Search isn’t available right now.")).toBeInTheDocument();
  });

  it("only applies the latest query", async () => {
    const fetch = searchFetch({ os: fixture("search-none"), osaka: fixture("search-osaka") });
    stubFetch(fetch);
    renderAt("/");
    const input = screen.getByLabelText("Airport name, city or code");
    for (const text of ["o", "os", "osa", "osak", "osaka"]) {
      fireEvent.change(input, { target: { value: text } });
      await settle(100); // typing faster than the 250 ms pause
    }
    await settle(250);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/2 airports found/)).toBeInTheDocument();
  });

  it("lists recently viewed airports and clears them", async () => {
    rememberAirport({ code: "KJFK", iata: "JFK", name: "John F. Kennedy International Airport" });
    rememberAirport({ code: "AAI", iata: "AAI", name: "Arraias Airport" });
    stubFetch(searchFetch({}));
    renderAt("/");
    const heading = screen.getByRole("heading", { name: "Recently viewed" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Arraias Airport · AAI" })).toHaveAttribute("href", "/airport/AAI");
    await act(async () => screen.getByRole("button", { name: "Clear" }).click());
    expect(screen.queryByText("Recently viewed")).not.toBeInTheDocument();
  });

  it("shows a code when a recent airport has no IATA code", () => {
    rememberAirport({ code: "EGKB", iata: null, name: "London Biggin Hill Airport" });
    stubFetch(searchFetch({}));
    renderAt("/");
    expect(screen.getByRole("link", { name: "London Biggin Hill Airport · EGKB" })).toBeInTheDocument();
  });
});

describe("not found page", () => {
  it("offers search for unknown paths", () => {
    renderAt("/nowhere");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(document.title).toBe("Page not found – ClearFlight");
  });
});

describe("airport page: forecast outlook (CF-008)", () => {
  function forecastSection() {
    return screen.getByRole("region", { name: "Forecast (next 12 hours)" });
  }

  function withForecast(name: string | "network") {
    forecastFetch = fixtureFetch(() => (name === "network" ? "network" : fixture(name)));
    stubFetch(fixtureFetch(() => fixture("conditions-egll-severe")));
  }

  it("shows 12 forecast hours in local time, labelled and styled apart from observed (F4)", async () => {
    withForecast("forecast-egll-fog");
    renderAt("/airport/EGLL");
    await settle();
    const section = forecastSection();
    const hours = within(section).getAllByRole("listitem");
    expect(hours).toHaveLength(12);
    expect(hours[0]).toHaveTextContent("07:00");
    expect(hours[0]).toHaveTextContent("10 / 10 Severe");
    expect(hours[1]).toHaveTextContent("Changing");
    expect(hours[5]).toHaveTextContent("2 / 10 Low");
    expect(hours[5]).toHaveTextContent("Up to 3 / 10 30% chance, temporarily");
    expect(within(section).getByText("Forecast conditions index · not observed weather")).toBeInTheDocument();
    // No filled level chips in the forecast; the observed card keeps its own.
    expect(section.querySelector("[class*='level-chip']")).toBeNull();
    expect(section.querySelectorAll(".forecast-hour")).toHaveLength(12);
    expect(within(section).getByText(/It is not observed weather and does not predict delays/)).toBeInTheDocument();
    expect(within(section).getByText("Issued 22:56 UTC · Valid until 06:00 UTC")).toBeInTheDocument();
  });

  it("shows an hour's factors and possible conditions when selected", async () => {
    withForecast("forecast-lfpg-possible");
    renderAt("/airport/EGLL");
    await settle();
    const first = within(forecastSection()).getAllByRole("button")[0]!;
    expect(first).toHaveTextContent("Up to 10 / 10");
    fireEvent.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");
    const details = screen.getByRole("region", { name: /Forecast details 07:00–08:00/ });
    expect(within(details).getByText(/Forecast conditions index 0\/10/)).toBeInTheDocument();
    expect(within(details).getByText(/Up to 10 \/ 10 \(30% chance, temporarily\):/)).toBeInTheDocument();
    expect(within(details).getByText(/07:00–08:00 local · 07:00–08:00 UTC/)).toBeInTheDocument();
    fireEvent.click(first);
    expect(screen.queryByRole("region", { name: /Forecast details/ })).not.toBeInTheDocument();
  });

  it("shows hours before the forecast starts as not yet valid (F5)", async () => {
    vi.setSystemTime(new Date("2026-10-29T22:10:00Z"));
    withForecast("forecast-rjbb-not-yet-valid");
    renderAt("/airport/EGLL");
    await settle();
    const hours = within(forecastSection()).getAllByRole("listitem");
    expect(hours[0]).toHaveTextContent("Forecast not yet valid");
    expect(hours[2]).toHaveTextContent("2 / 10 Low");
  });

  it("removes hours as they end, and withdraws an expired forecast", async () => {
    withForecast("forecast-egll-fog");
    renderAt("/airport/EGLL");
    await settle();
    expect(within(forecastSection()).getAllByRole("listitem")[0]).toHaveTextContent("07:00");
    await settle(5 * 60 * 1000 + 1); // 08:00:00.001
    expect(within(forecastSection()).getAllByRole("listitem")[0]).toHaveTextContent("08:00");
    expect(within(forecastSection()).getAllByRole("listitem")).toHaveLength(11);
    forecastFetch = fixtureFetch(() => "network"); // refreshes now fail
    await settle(11 * 60 * 60 * 1000); // 19:00: every hour has ended
    expect(within(forecastSection()).getByText("The latest forecast has expired.")).toBeInTheDocument();
  });

  it("keeps the remaining hours and says so when a forecast refresh fails", async () => {
    withForecast("forecast-egll-fog");
    renderAt("/airport/EGLL");
    await settle();
    forecastFetch = fixtureFetch(() => "network");
    await settle(5 * 60 * 1000);
    expect(within(forecastSection()).getByText(/Couldn’t update the forecast just now — showing the forecast issued 22:56 UTC/)).toBeInTheDocument();
    expect(within(forecastSection()).getAllByRole("listitem")).toHaveLength(11);
  });

  it.each([
    ["forecast-rjbb-no-forecast", "No forecast is available for this airport right now."],
    ["forecast-egll-expired", "The latest forecast has expired."],
  ])("explains %s", async (name, text) => {
    withForecast(name);
    renderAt("/airport/EGLL");
    await settle();
    expect(within(forecastSection()).getByText(text)).toBeInTheDocument();
  });

  it("shows nothing extra when the airport has no station", async () => {
    forecastFetch = fixtureFetch(() => fixture("forecast-aai-no-station"));
    stubFetch(fixtureFetch(() => fixture("conditions-aai-no-station")));
    renderAt("/airport/AAI");
    await settle();
    expect(screen.queryByRole("region", { name: "Forecast (next 12 hours)" })).not.toBeInTheDocument();
  });

  it("offers a retry when the forecast can't load, without affecting the conditions", async () => {
    withForecast("network");
    renderAt("/airport/EGLL");
    await settle();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(within(forecastSection()).getByText("The forecast couldn’t be loaded just now.")).toBeInTheDocument();
    forecastFetch = fixtureFetch(() => fixture("forecast-egll-fog"));
    fireEvent.click(within(forecastSection()).getByRole("button", { name: "Try again" }));
    await settle();
    expect(within(forecastSection()).getAllByRole("listitem")).toHaveLength(12);
  });

  it("refreshes the forecast with the Refresh button", async () => {
    withForecast("forecast-egll-fog");
    renderAt("/airport/EGLL");
    await settle();
    expect(forecastFetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await settle();
    expect(forecastFetch).toHaveBeenCalledTimes(2);
  });
});
