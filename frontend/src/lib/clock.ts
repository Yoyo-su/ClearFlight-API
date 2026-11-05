// Airport-local and UTC clocks from an IANA timezone; Intl applies the zone's
// DST rules, so no offsets are hard-coded (plan §2).

export interface ClockReading {
  time: string; // "08:20"
  date: string; // "Mon 2 Nov"
  zone: string; // "GMT (UTC+0)", "EDT (UTC−4)", "UTC−3"
}

function part(parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes): string {
  return parts.find((p) => p.type === type)?.value ?? "";
}

/** "UTC+9", "UTC−4", "UTC+5:30" from Intl's "GMT+09:00" style offset. */
function utcOffset(timeZone: string, now: Date): string {
  const name = part(
    new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "longOffset" }).formatToParts(now),
    "timeZoneName",
  );
  const match = /GMT([+-])(\d{2}):(\d{2})/.exec(name);
  if (!match) return "UTC+0";
  const [, sign, hours, minutes] = match;
  const text = `${Number(hours)}${minutes === "00" ? "" : `:${minutes}`}`;
  return `UTC${sign === "-" ? "−" : "+"}${text}`;
}

function zoneLabel(timeZone: string, now: Date, style: "short" | "long", locale: string): string {
  return part(new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: style }).formatToParts(now), "timeZoneName");
}

/**
 * A zone name such as "BST" or "EDT" if the browser knows an abbreviation,
 * otherwise its full name such as "Greenwich Mean Time" or "Japan Standard
 * Time". Which names a browser knows varies (Playwright's headless Chromium
 * knows none and gives "GMT+0"), and guessing one would be wrong for zones
 * such as Lisbon (WET), so the full name is the fallback. Null when the
 * browser only knows an offset.
 */
function zoneName(timeZone: string, now: Date): string | null {
  // "GMT+1"/"UTC−4" are offsets, not names; a bare "GMT" is a real name
  // (London in winter), a bare "UTC" isn't one for a local zone.
  const isOffset = (name: string) => /^(GMT|UTC)[+−-]/.test(name) || name === "UTC";
  for (const locale of ["en-GB", "en-US"]) {
    const name = zoneLabel(timeZone, now, "short", locale);
    if (name && !isOffset(name)) return name;
  }
  const long = zoneLabel(timeZone, now, "long", "en-GB");
  return long && !isOffset(long) ? long : null;
}

export function readClock(timeZone: string, now: Date): ClockReading {
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(now);
  const date = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "short",
  })
    .format(now)
    .replace(",", "");
  const offset = utcOffset(timeZone, now);
  const name = zoneName(timeZone, now);
  return { time, date, zone: name ? `${name} (${offset})` : offset };
}

export function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone });
    return true;
  } catch {
    return false;
  }
}
