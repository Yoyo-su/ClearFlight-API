import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta

"""
Live aircraft positions near an airport: the shared model, area maths,
classification and the state rules (CF-009 design r3 §3-§4).

Provider adapters (positions_providers.py) return a FeedResult; the service
(positions_service.py) caches it and this module turns it into what can be
shown at a given moment. Expiry is per position and checked at every read.
"""

EARTH_RADIUS_NM = 3440.065
FEET_PER_METRE = 3.28084
KNOTS_PER_MPS = 1.943844
FPM_PER_MPS = 196.8504

ID_PATTERN = re.compile(r"~?[0-9a-f]{6}")
CALLSIGN_PATTERN = re.compile(r"[A-Z0-9]{2,8}")
AIRCRAFT_CATEGORIES = {f"A{n}" for n in range(1, 8)} | {f"B{n}" for n in range(1, 8)}
SURFACE_CATEGORIES = {f"C{n}" for n in range(1, 8)}
SURFACE_TYPES = {"TWR", "GND"}  # adsb.lol type codes for ground stations


@dataclass(frozen=True)
class Area:
    latitude: float
    longitude: float
    radius_nm: float

    def boxes(self) -> list[tuple[float, float, float, float]]:
        """Bounding boxes (lamin, lomin, lamax, lomax) covering the circle.

        Split in two where the box crosses the antimeridian.
        """
        dlat = self.radius_nm / 60
        cos_lat = max(math.cos(math.radians(self.latitude)), 0.01)
        dlon = min(self.radius_nm / (60 * cos_lat), 180)
        lamin = max(self.latitude - dlat, -90.0)
        lamax = min(self.latitude + dlat, 90.0)
        lomin, lomax = self.longitude - dlon, self.longitude + dlon
        if dlon >= 180:
            return [(lamin, -180.0, lamax, 180.0)]
        if lomin < -180:
            return [(lamin, lomin + 360, lamax, 180.0), (lamin, -180.0, lamax, lomax)]
        if lomax > 180:
            return [(lamin, lomin, lamax, 180.0), (lamin, -180.0, lamax, lomax - 360)]
        return [(lamin, lomin, lamax, lomax)]


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class Target:
    id: str
    callsign: str | None
    latitude: float
    longitude: float
    altitude_ft: int | None
    on_ground: bool
    ground_speed_kt: int | None
    track_deg: int | None
    vertical_rate_fpm: int | None
    category: str | None
    kind: str  # "aircraft" | "unclassified"
    position_at: datetime
    distance_nm: float


@dataclass
class FeedResult:
    """One provider answer for an area, after normalisation and filtering."""

    provider: str
    access: str  # "keyless" | "anonymous" | "account"
    observed_at: datetime  # the provider's data time
    fetched_at: datetime
    targets: list[Target] = field(default_factory=list)
    withheld: int = 0  # privacy (LADD/PIA)
    excluded: int = 0  # surface vehicles, towers
    dropped: int = 0  # invalid or expired positions
    airborne: int = 0  # airborne targets seen (coverage evidence)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["observed_at"] = self.observed_at.isoformat()
        data["fetched_at"] = self.fetched_at.isoformat()
        for target in data["targets"]:
            target["position_at"] = target["position_at"].isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "FeedResult":
        targets = [
            Target(**{**t, "position_at": datetime.fromisoformat(t["position_at"])})
            for t in data["targets"]
        ]
        return cls(
            **{
                **data,
                "observed_at": datetime.fromisoformat(data["observed_at"]),
                "fetched_at": datetime.fromisoformat(data["fetched_at"]),
                "targets": targets,
            }
        )


def finite(value, low: float, high: float) -> float | None:
    """value if it is a finite number within [low, high], else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or not low <= value <= high:
            return None
    except OverflowError:
        return None
    return float(value)


def whole(value: float | None) -> int | None:
    return None if value is None else round(value)


def clean_callsign(value) -> str | None:
    """Trimmed callsign; None when empty or a placeholder like @@@@@@@@."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    return text if CALLSIGN_PATTERN.fullmatch(text) else None


def classify(category: str | None, type_code: str | None = None) -> str:
    """aircraft, surface (excluded) or unclassified (spec §3)."""
    if category in SURFACE_CATEGORIES or type_code in SURFACE_TYPES:
        return "surface"
    if category in AIRCRAFT_CATEGORIES:
        return "aircraft"
    return "unclassified"


class Collector:
    """Builds a FeedResult row by row, applying the spec §3 filters in order."""

    def __init__(self, area: Area, max_age_s: int, observed_at: datetime):
        self.area = area
        self.max_age = timedelta(seconds=max_age_s)
        self.observed_at = observed_at
        self.targets: list[Target] = []
        self.withheld = self.excluded = self.dropped = self.airborne = 0

    def add(self, row: dict | None, *, withheld: bool = False, type_code=None) -> None:
        """Add one normalised row (None = invalid, counted as dropped).

        Rows outside the area are ignored entirely; privacy comes first, then
        classification, then position age.
        """
        if row is None:
            self.dropped += 1
            return
        dist = distance_nm(
            self.area.latitude, self.area.longitude, row["latitude"], row["longitude"]
        )
        if dist > self.area.radius_nm:
            return
        if withheld:
            self.withheld += 1
            return
        kind = classify(row["category"], type_code)
        if kind == "surface":
            self.excluded += 1
            return
        if self.observed_at - row["position_at"] >= self.max_age:
            self.dropped += 1
            return
        if not row["on_ground"]:
            self.airborne += 1
        self.targets.append(Target(**row, kind=kind, distance_nm=round(dist, 2)))

    def result(self, provider: str, access: str, fetched_at: datetime) -> FeedResult:
        return FeedResult(
            provider=provider,
            access=access,
            observed_at=self.observed_at,
            fetched_at=fetched_at,
            targets=sorted(self.targets, key=lambda t: t.distance_nm),
            withheld=self.withheld,
            excluded=self.excluded,
            dropped=self.dropped,
            airborne=self.airborne,
        )


def visible(result: FeedResult, now: datetime, max_age_s: int) -> FeedResult:
    """The result as it may be shown at `now`: expired positions are dropped."""
    limit = timedelta(seconds=max_age_s)
    shown = [t for t in result.targets if now - t.position_at < limit]
    expired = len(result.targets) - len(shown)
    return replace(result, targets=shown, dropped=result.dropped + expired)


def assess(
    result: FeedResult, now: datetime, max_age_s: int, coverage_evidence: bool
) -> tuple[str, str | None]:
    """(data_status, reason) for a visible result at `now` (spec §4)."""
    if result.targets or result.withheld:
        return "available", None
    if result.dropped:
        return "coverage_unknown", "unusable_data"
    if abs((now - result.observed_at).total_seconds()) > max_age_s:
        return "coverage_unknown", "stale_feed"
    if not coverage_evidence:
        return "coverage_unknown", "no_coverage_evidence"
    return "no_aircraft", None
