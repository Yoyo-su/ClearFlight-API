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

/** A short zone name such as "GMT", "BST" or "EDT", if the platform knows one. */
function abbreviation(timeZone: string, now: Date): string | null {
  for (const locale of ["en-GB", "en-US"]) {
    const name = part(
      new Intl.DateTimeFormat(locale, { timeZone, timeZoneName: "short" }).formatToParts(now),
      "timeZoneName",
    );
    if (name && !/^(GMT|UTC)[+−-]/.test(name)) return name === "UTC" ? "GMT" : name;
  }
  return null;
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
  const short = abbreviation(timeZone, now);
  return { time, date, zone: short ? `${short} (${offset})` : offset };
}

export function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone });
    return true;
  } catch {
    return false;
  }
}
