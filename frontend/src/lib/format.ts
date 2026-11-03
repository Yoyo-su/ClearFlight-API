import type { CloudLayer, Observation } from "../api/types";

// Display formatting for observations: both unit systems, metric first (D1).

const NOT_REPORTED = "Not reported";
const METRES_PER_MILE = 1609.344;
const KMH_PER_KT = 1.852;
const METRES_PER_FT = 0.3048;

function number(value: number, decimals = 0): string {
  return value.toLocaleString("en-GB", {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

export function formatTemperature(celsius: number | null): string {
  if (celsius === null) return NOT_REPORTED;
  const fahrenheit = Math.round((celsius * 9) / 5 + 32);
  return `${number(celsius, 1)} °C (${fahrenheit} °F)`;
}

function knots(kt: number): string {
  return `${kt} kt (${Math.round(kt * KMH_PER_KT)} km/h)`;
}

export function formatWind(obs: Observation): string {
  if (obs.wind_speed_kt === null) return NOT_REPORTED;
  if (obs.wind_speed_kt === 0) return "Calm";
  if (obs.wind_variable) return `Variable at ${knots(obs.wind_speed_kt)}`;
  if (obs.wind_direction_deg === null) return `${knots(obs.wind_speed_kt)}, direction not reported`;
  const direction = String(obs.wind_direction_deg).padStart(3, "0");
  return `From ${direction}° at ${knots(obs.wind_speed_kt)}`;
}

export function formatGusts(gust: number | null): string {
  return gust === null ? "None reported" : knots(gust);
}

export function formatVisibility(metres: number | null, atLeast: boolean): string {
  if (metres === null) return NOT_REPORTED;
  const metric = metres >= 1000 ? `${number(metres / 1000, 1)} km` : `${metres} m`;
  const miles = `${number(metres / METRES_PER_MILE, 1)} mi`;
  return atLeast ? `${metric} or more (${miles} or more)` : `${metric} (${miles})`;
}

export function formatHeight(feet: number): string {
  return `${number(feet)} ft (${number(Math.round((feet * METRES_PER_FT) / 10) * 10)} m)`;
}

const COVER_WORDS: Record<string, string> = {
  FEW: "Few clouds",
  SCT: "Scattered clouds",
  BKN: "Broken cloud",
  OVC: "Overcast",
};

function layer(cloud: CloudLayer): string {
  return `${COVER_WORDS[cloud.cover] ?? cloud.cover} at ${number(cloud.base_ft)} ft`;
}

export function formatCloud(obs: Observation): string {
  switch (obs.sky_condition) {
    case "clear":
      return "No cloud detected";
    case "cavok":
      return "CAVOK: no significant cloud";
    case "obscured":
      return "Sky obscured; height not reported";
    case "unknown":
      return NOT_REPORTED;
    default:
      return obs.cloud_layers.length ? obs.cloud_layers.map(layer).join(", ") : NOT_REPORTED;
  }
}

export function formatCeiling(obs: Observation): string {
  if (obs.sky_condition === "obscured" || obs.sky_condition === "unknown") return NOT_REPORTED;
  return obs.ceiling_ft === null ? "No ceiling" : formatHeight(obs.ceiling_ft);
}

export function formatPressure(hpa: number | null): string {
  return hpa === null ? NOT_REPORTED : `${number(hpa, 1)} hPa`;
}

const INTENSITY: Record<string, string> = { "-": "Light", "+": "Heavy" };
const DESCRIPTOR: Record<string, string> = {
  MI: "shallow",
  PR: "partial",
  BC: "patches of",
  DR: "low drifting",
  BL: "blowing",
  FZ: "freezing",
};
const PHENOMENA: Record<string, string> = {
  DZ: "drizzle",
  RA: "rain",
  SN: "snow",
  SG: "snow grains",
  IC: "ice crystals",
  PL: "ice pellets",
  GR: "hail",
  GS: "small hail",
  UP: "unknown precipitation",
  BR: "mist",
  FG: "fog",
  FU: "smoke",
  VA: "volcanic ash",
  DU: "dust",
  SA: "sand",
  HZ: "haze",
  PY: "spray",
  PO: "dust whirls",
  SQ: "squalls",
  FC: "funnel cloud",
  SS: "sandstorm",
  DS: "duststorm",
};
const GROUP = /^(-|\+|VC)?(MI|PR|BC|DR|BL|SH|TS|FZ)?((?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)$/;

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Plain-English wording for one METAR weather group, e.g. "+SHRA". */
export function describeWeather(group: string): string {
  const match = GROUP.exec(group);
  if (!match || (!match[3] && match[2] !== "TS" && match[2] !== "SH")) {
    return `${group} (not recognised)`;
  }
  const [, intensity, descriptor, codes = ""] = match;
  const things = (codes.match(/../g) ?? []).map((code) => PHENOMENA[code] ?? code).join(" and ");
  let text: string;
  if (descriptor === "TS") text = things ? `thunderstorm with ${things}` : "thunderstorm";
  else if (descriptor === "SH") text = things ? `${things} showers` : "showers";
  else text = descriptor ? `${DESCRIPTOR[descriptor]} ${things}` : things;
  if (intensity && intensity !== "VC") text = `${INTENSITY[intensity]} ${text}`;
  if (intensity === "VC") text = `${text} in the vicinity`;
  return `${capitalise(text)} (${group})`;
}

export function formatWeather(groups: string[]): string {
  return groups.length ? groups.map(describeWeather).join(", ") : "None reported";
}

/** "07:20 UTC" from an ISO timestamp. */
export function formatUtcTime(iso: string): string {
  return `${new Date(iso).toISOString().slice(11, 16)} UTC`;
}

/** Whole minutes since `iso`, rounded up (matches the API's age_minutes). */
export function minutesSince(iso: string, now: Date): number {
  return Math.max(0, Math.ceil((now.getTime() - new Date(iso).getTime()) / 60000));
}

/** "35 min", "2 h 5 min", "4 h". */
export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export function formatAgo(iso: string, now: Date): string {
  const minutes = minutesSince(iso, now);
  return minutes === 0 ? "just now" : `${formatDuration(minutes)} ago`;
}
