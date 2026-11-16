"""P5 comparison, CF-011 design §9 as amended 2026-11-15 (identity by flight
number, then airline + aircraft type + movement). Fixed before the fresh
recordings it is applied to.

Usage:
  p5_compare.py BOARD_KIND DETECTED.json RECORDING_DIR BOARD_DIR AIRPORT_IATA HOUR_START_UTC
    BOARD_KIND: heathrow | jfk
    DETECTED.json: movements from scripts/replay_movements.py --json
    RECORDING_DIR: the raw adsb.lol polls (aircraft type `t` by hex, offline only)
    BOARD_DIR: the captured board files
Prints the result as JSON.
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HOUR = timedelta(hours=1)
SLACK = timedelta(minutes=45)
M = lambda n: timedelta(minutes=n)  # noqa: E731
TOL = {
    "airborne": (M(-5), M(5)),
    "landed": (M(-5), M(5)),
    "offblock": (M(0), M(45)),
    "onblock": (M(-30), M(0)),
    "dep_unknown": (M(-5), M(45)),  # time type not stated: either departure tolerance
    "arr_unknown": (M(-30), M(5)),  # either arrival tolerance
    "dep_scheduled": (M(-15), M(75)),
    "arr_scheduled": (M(-60), M(30)),
}
ALIASES = {"SHT": "BAW"}  # callsign prefix -> board airline (BA Shuttle flies as BA)
# IATA -> ICAO airline codes for boards that give IATA only (fixed table, §9).
IATA_TO_ICAO = {
    "AA": "AAL",
    "DL": "DAL",
    "UA": "UAL",
    "B6": "JBU",
    "AS": "ASA",
    "WN": "SWA",
    "NK": "NKS",
    "F9": "FFT",
    "SY": "SCX",
    "HA": "HAL",
    "AC": "ACA",
    "WS": "WJA",
    "AM": "AMX",
    "Y4": "VOI",
    "BA": "BAW",
    "VS": "VIR",
    "AF": "AFR",
    "KL": "KLM",
    "LH": "DLH",
    "LX": "SWR",
    "OS": "AUA",
    "SN": "BEL",
    "IB": "IBE",
    "AZ": "ITY",
    "TP": "TAP",
    "EI": "EIN",
    "SK": "SAS",
    "AY": "FIN",
    "TK": "THY",
    "EK": "UAE",
    "EY": "ETD",
    "QR": "QTR",
    "SV": "SVA",
    "MS": "MSR",
    "RJ": "RJA",
    "LY": "ELY",
    "ET": "ETH",
    "KQ": "KQA",
    "AT": "RAM",
    "AI": "AIC",
    "CX": "CPA",
    "JL": "JAL",
    "NH": "ANA",
    "KE": "KAL",
    "OZ": "AAR",
    "CI": "CAL",
    "BR": "EVA",
    "CA": "CCA",
    "MU": "CES",
    "CZ": "CSN",
    "SQ": "SIA",
    "QF": "QFA",
    "NZ": "ANZ",
    "LA": "LAN",
    "AV": "AVA",
    "CM": "CMP",
    "AR": "ARG",
    "G3": "GLO",
    "CU": "CUB",
    "BW": "BWA",
    "UX": "AEA",
    "VY": "VLG",
    "PD": "POE",
    "MX": "MXY",
    "XP": "CXP",
    "DE": "CFG",
    "LO": "LOT",
    "PR": "PAL",
    "VN": "HVN",
    "GA": "GIA",
    "TG": "THA",
    "MH": "MAS",
    "5X": "UPS",
    "FX": "FDX",
    "K4": "CKS",
    "PO": "PAC",
    "CV": "CLX",
    # Kansai (added 2026-11-15, before the RJBB hour): low-cost and regional carriers
    "MM": "APJ",
    "RS": "ASV",
    "7C": "JJA",
    "LJ": "JNA",
    "ZE": "ESR",
    "BX": "ABL",
    "TW": "TWB",
    "IT": "TTW",
    "XJ": "TAX",
    "TR": "TGW",
    "VZ": "TVJ",
    "MQ": "SFJ",
    "FM": "CSH",
    "GK": "JJP",
    "BC": "SKY",
    "7G": "SFJ",
    "HX": "CRK",
    "UO": "HKE",
    "FD": "AIQ",
    "Z2": "APG",
    "5J": "CEB",
    "D7": "XAX",
    "VJ": "VJC",
    "HO": "DKH",
    "9C": "CQH",
    "OM": "MGL",
    "NX": "AMU",
    "KA": "HDA",
    "NU": "JTA",
    "IJ": "SJO",
    "RF": "EOK",
    "OD": "MXD",
}


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def number_id(callsign: str | None) -> str | None:
    """ICAO prefix + flight number without leading zeros, or None."""
    if not callsign:
        return None
    m = re.fullmatch(r"([A-Z]{3})0*(\d{1,4})", callsign.strip().upper())
    return f"{m.group(1)}{m.group(2)}" if m else None


# -- Boards: each entry {flight, id, airline, type, kind, time, time_type, status}


def heathrow(board_dir: str, iata: str) -> list[dict]:
    keys = {"departure": {"Departed": "airborne"}, "arrival": {"Landed": "landed"}}
    out = []
    for kind, name in (("departure", "departures"), ("arrival", "arrivals")):
        port_type = "ORIGIN" if kind == "departure" else "DESTINATION"
        for f in json.load(open(os.path.join(board_dir, f"{name}.flights.json"))):
            s = f["flightService"]
            if s.get("codeShareStatus", "").startswith("CODESHARE_MARKETING"):
                continue
            statuses = s["aircraftMovement"].get("aircraftMovementStatus", [])
            text = " ".join(x.get("message", "") for x in statuses)
            if "cancel" in text.lower():
                continue
            port = next(
                p for p in s["aircraftMovement"]["route"]["portsOfCall"]
                if p["portOfCallType"] == port_type and p["airportFacility"]["iataIdentifier"] == iata
            )  # fmt: skip
            sched = utc(port["operatingTimes"]["scheduled"]["utc"])
            offset = utc(port["operatingTimes"]["scheduled"]["local"]) - sched
            when, ttype = sched, (
                "dep_scheduled" if kind == "departure" else "arr_scheduled"
            )
            for st in statuses:
                for item in st.get("statusData", []):
                    t = keys[kind].get(item.get("localisationKey"))
                    if t and re.fullmatch(r"\d{2}:\d{2}", item.get("data", "")):
                        h, mnt = map(int, item["data"].split(":"))
                        local = (sched + offset).replace(hour=h, minute=mnt)
                        for shift in (timedelta(days=-1), timedelta(days=1)):
                            if abs(local + shift - sched - offset) < abs(
                                local - sched - offset
                            ):
                                local += shift
                        when, ttype = local - offset, t
            icao = s["icaoFlightIdentifier"]
            out.append(
                {"flight": icao, "id": number_id(icao), "airline": icao[:3],
                 "type": (s.get("aircraftTransport") or {}).get("icaoTypeCode"),
                 "kind": kind, "time": when, "time_type": ttype, "status": text[:60]}
            )  # fmt: skip
    return out


def jfk(board_dir: str, iata: str) -> list[dict]:
    """JFK flight tracker lists. Times are local gate times ("Departed",
    "Arrived": type not stated, so the wider tolerances); codeshare rows of one
    movement (same scheduled time, other airport, terminal and gate) collapse."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/New_York")

    def local(date: str, hhmm: str) -> datetime:
        t = datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %I:%M %p").replace(tzinfo=tz)
        return t.astimezone(timezone.utc)

    groups: dict[tuple, list] = {}
    for f in sorted(glob.glob(os.path.join(board_dir, "*.json"))):
        page = json.load(open(f))
        kind = "departure" if page["tab"] == "DEPARTURES" else "arrival"
        for row in page["flights"]:
            other = (
                row.get("destinationAirportCode")
                if kind == "departure"
                else row.get("originAirportCode")
            )
            key = (
                kind,
                row["dateScheduled"],
                row["timeScheduled"],
                other,
                row.get("terminal"),
                row.get("gate"),
            )
            if row not in groups.setdefault(key, []):
                groups[key].append(row)
    out = []
    done = {"departure": "Departed", "arrival": "Arrived"}
    for (kind, date, sched_text, other, _, _), rows in groups.items():
        if all(r["status"] == "Cancelled" for r in rows):
            continue
        sched = local(date, sched_text)
        when, ttype = sched, (
            "dep_scheduled" if kind == "departure" else "arr_scheduled"
        )
        for r in rows:
            if r["status"] == done[kind] and r.get("timeRevised"):
                t = local(r.get("dateRevised") or date, r["timeRevised"])
                for shift in (timedelta(days=-1), timedelta(days=1)):
                    if abs(t + shift - sched) < abs(t - sched):
                        t += shift
                when, ttype = t, (
                    "dep_unknown" if kind == "departure" else "arr_unknown"
                )
        ids = {
            f"{IATA_TO_ICAO[r['airlineCode']]}{int(r['flightNumber'])}"
            for r in rows
            if r["airlineCode"] in IATA_TO_ICAO
        }
        flights = "/".join(
            sorted(f"{r['airlineCode']}{r['flightNumber']}" for r in rows)
        )
        out.append(
            {"flight": flights, "id": None, "ids": ids, "airline": None, "type": None,
             "kind": kind, "time": when, "time_type": ttype, "status": rows[0]["status"],
             "unmapped": sorted({r["airlineCode"] for r in rows if r["airlineCode"] not in IATA_TO_ICAO})}
        )  # fmt: skip
    return out


def kansai(board_dir: str, iata: str) -> list[dict]:
    """Kansai boards pasted by the owner (V5) into RJBB-board*.txt as pipe rows:
    flights (operating first, then codeshares) | other city | scheduled | revised | status.
    Local JST; "DEPARTED"/"ARRIVED" times don't state their type (wider tolerances)."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Tokyo")
    date = os.environ.get("BOARD_DATE", "2026-11-16")

    def local(hhmm: str) -> datetime:
        return (
            datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M")
            .replace(tzinfo=tz)
            .astimezone(timezone.utc)
        )

    out = []
    for path in sorted(glob.glob(os.path.join(board_dir, "RJBB-board*.txt"))):
        kind = None
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("## "):
                kind = "departure" if "DEPARTURES" in line else "arrival"
                continue
            if not line or line.startswith("#"):
                continue
            flights, _, sched, revised, status = (line.split("|") + [""] * 5)[:5]
            if "CANCEL" in status.upper():
                continue  # never operated: not a board movement
            done = status == ("DEPARTED" if kind == "departure" else "ARRIVED")
            if done and revised:
                when, ttype = local(revised), (
                    "dep_unknown" if kind == "departure" else "arr_unknown"
                )
            else:
                when, ttype = local(sched), (
                    "dep_scheduled" if kind == "departure" else "arr_scheduled"
                )
            ids = set()
            for code in flights.split():
                m = re.fullmatch(r"([A-Z0-9]{2})(\d{1,4})", code)
                if m and m.group(1) in IATA_TO_ICAO:
                    ids.add(f"{IATA_TO_ICAO[m.group(1)]}{int(m.group(2))}")
            out.append(
                {"flight": flights, "id": None, "ids": ids, "airline": None, "type": None, "kind": kind,
                 "time": when, "time_type": ttype, "status": status,
                 "unmapped": sorted({c[:2] for c in flights.split() if c[:2] not in IATA_TO_ICAO})}
            )  # fmt: skip
    return out


BOARDS = {"heathrow": heathrow, "jfk": jfk, "kansai": kansai}

# -- Matching


def identify(d: dict, b: dict) -> int | None:
    if d["kind"] != b["kind"]:
        return None
    if d["id"] is not None and (d["id"] == b["id"] or d["id"] in b.get("ids", ())):
        return 0
    if (
        b["type"]
        and d["type"]
        and d["airline"]
        and ALIASES.get(d["airline"], d["airline"]) == b["airline"]
        and d["type"] == b["type"]
    ):
        return 1
    return None


def match(det: list[dict], board: list[dict]) -> dict[int, tuple[int, int]]:
    pairs = []
    for i, d in enumerate(det):
        for j, b in enumerate(board):
            how = identify(d, b)
            if how is None:
                continue
            lo, hi = TOL[b["time_type"]]
            diff = d["time"] - b["time"]
            if lo <= diff <= hi:
                pairs.append((how, abs(diff), i, j))
    pairs.sort()
    out, used = {}, set()
    for how, _, i, j in pairs:
        if i not in out and j not in used:
            out[i] = (j, how)
            used.add(j)
    return out


def main() -> int:
    kind, det_path, rec_dir, board_dir, iata, hour = sys.argv[1:7]
    start = utc(hour)
    end = start + HOUR
    types = {}
    for f in sorted(glob.glob(os.path.join(rec_dir, "*.json"))):
        for a in json.load(open(f)).get("ac", []):
            if a.get("t"):
                types[a["hex"]] = a["t"]
    board = BOARDS[kind](board_dir, iata)
    board_has_types = any(b["type"] for b in board)
    has_actual = any(
        not b["time_type"].endswith("scheduled")
        for b in board
        if start <= b["time"] < end
    )
    det = []
    for m in json.load(open(det_path)):
        t = utc(m["time_from"]) + (utc(m["time_to"]) - utc(m["time_from"])) / 2
        if start - SLACK <= t < end + SLACK:
            cs = (m.get("callsign") or "").strip().upper() or None
            det.append(
                {
                    **m,
                    "callsign": cs,
                    "time": t,
                    "id": number_id(cs),
                    "airline": cs[:3] if cs else None,
                    "type": types.get(m["id"]),
                }
            )
    matched = match(det, board)
    used = {j for j, _ in matched.values()}

    def in_hour(t):
        return start <= t < end

    def counted(
        b,
    ):  # scheduled-only flights leave the denominator when the board has actual times
        return in_hour(b["time"]) and not (
            has_actual and b["time_type"].endswith("scheduled")
        )

    def identified(d):
        return d["id"] is not None or (
            board_has_types and d["airline"] is not None and d["type"] is not None
        )

    def figures(method=None):
        bh = [j for j, b in enumerate(board) if counted(b)]
        dh = [
            i
            for i, d in enumerate(det)
            if in_hour(d["time"]) and method in (None, d["method"])
        ]
        unid = [i for i in dh if i not in matched and not identified(det[i])]
        ident = [i for i in dh if i not in unid]
        found = sum(
            1
            for j in bh
            if j
            in {matched[i][0] for i in matched if method in (None, det[i]["method"])}
        )
        false = sum(1 for i in ident if i not in matched)
        return {
            "board": len(bh), "matched": found, "found": round(found / len(bh), 3) if bh else None,
            "detections": len(ident), "unmatched": false, "false": round(false / len(ident), 3) if ident else None,
            "unidentified": len(unid),
        }  # fmt: skip

    # §9 (P5-b): a board where under 80% of the hour's movements carry a usable
    # identity (a flight number we can map, or an aircraft type for rule 2) isn't compared.
    hour_board = [b for b in board if counted(b)]
    with_identity = [
        b
        for b in hour_board
        if b.get("id") or b.get("ids") or (b.get("type") and b.get("airline"))
    ]
    share = len(with_identity) / len(hour_board) if hour_board else 0.0
    if share < 0.8:
        print(json.dumps({"result": "not assessed", "reason": f"board identity coverage {share:.0%} < 80% (§9)",
                          "board": len(hour_board), "with_identity": len(with_identity)}, indent=1))  # fmt: skip
        return 2

    result = {
        "rule": "§9 2026-11-15: flight number, then airline + aircraft type + movement",
        "board_identity_coverage": round(share, 3),
        "hour": [start.isoformat(), end.isoformat()],
        "evidence": "actual times" if has_actual else "scheduled-time comparison (weaker evidence)",
        "board_types_available": board_has_types,
        "combined": figures(), "observed": figures("observed"), "inferred": figures("inferred"),
        "matched_by": {"flight_number": sum(1 for _, h in matched.values() if h == 0), "airline_type": sum(1 for _, h in matched.values() if h == 1)},
        "missed_board": [
            {"flight": b["flight"], "kind": b["kind"], "time": b["time"].isoformat(), "time_type": b["time_type"], "type": b["type"]}
            for j, b in enumerate(board) if counted(b) and j not in used
        ],
        "unmatched_detections": [
            {"callsign": d["callsign"], "kind": d["kind"], "method": d["method"], "time": d["time"].isoformat(), "type": d["type"],
             "identified": identified(d)}
            for i, d in enumerate(det) if in_hour(d["time"]) and i not in matched
        ],
        "matches": [
            {"callsign": det[i]["callsign"], "flight": board[j]["flight"], "kind": board[j]["kind"],
             "by": "flight_number" if h == 0 else "airline_type",
             "detected": det[i]["time"].isoformat(), "board": board[j]["time"].isoformat(), "time_type": board[j]["time_type"]}
            for i, (j, h) in sorted(matched.items(), key=lambda x: det[x[0]]["time"]) if in_hour(det[i]["time"])
        ],
    }  # fmt: skip
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
