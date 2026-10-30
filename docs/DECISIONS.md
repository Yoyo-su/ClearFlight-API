# Decisions log

Record technical and product decisions that constrain future work. Add new entries at the top. Each entry needs a date, the decision, the reason and a source (plan section, PR or issue). Do not record decisions here that have not actually been made.

Locked pilot decisions live in [development-plan.md §1](development-plan.md) and are not repeated here. Changing them requires a plan version increment (plan §11 change policy).

## Format

```markdown
### D-NNN: <title> (YYYY-MM-DD)
- **Decision:**
- **Why:**
- **Alternatives considered:**
- **Source:** PR #/issue #/plan §
- **Status:** accepted | superseded by D-NNN
```

## Entries

### D-006: METAR observation contract, caching, rate cap and error mapping (2026-10-30)
- **Decision:**
  - **Source:** Aviation Weather Center `api/data/metar?ids={ICAO}&format=json`. The newest record by `obsTime` becomes `observed_at` (not `reportTime`, which can differ). Records more than 10 minutes in the future are ignored. 204 means no report and returns `None`, not an error.
  - **Units:** °C, kt (AWC converts MPS), metres for visibility (converted from statute miles; `visibility_at_least` for `N+`), feet for cloud bases, hPa.
  - **Validity rules:** each number must be finite and not a bool, within these ranges: temperature/dew point −90…60, direction 0…360, speed 0…250, gust 0…300 and not below the speed, visibility ≥ 0, pressure 850…1100, cloud base ≥ 0. Anything else becomes `null` for that field only. `rawOb` is never parsed for missing values.
  - **Sky:** `sky_condition` is `clear` (CLR/SKC/NCD/NSC), `cavok`, `clouds`, `obscured` (OVX) or `unknown`. `ceiling_ft` is the lowest BKN/OVC base, so a null ceiling must be read together with `sky_condition`. A BKN/OVC layer with a missing or invalid base makes `sky_condition` `unknown` with a null ceiling, because the ceiling could be at that unknown height.
  - **Freshness:** current ≤ 90 min, stale ≤ 180 min, then expired. These are configurable and computed at read time.
  - **Cache:** the normalised observation for 600 s and "no report" for 300 s. Malformed cached values are treated as misses. "No report" is cached only for a 204 or an empty list; a response whose records are all unusable returns `None` without caching, so it's retried on the next request (bounded by the rate cap).
  - **Provider protection:** User-Agent `METAR_USER_AGENT`; one retry after 0.5 s plus jitter on timeouts, connection errors, 429 (Retry-After capped at 2 s) and 5xx; an in-process token bucket of 30 requests/min, which retries also use.
  - **Status mapping for CF-004:** `MetarTimeout` → 504; `MetarUpstreamError` → 502; `MetarRateLimited` → **503 with Retry-After** (429 stays reserved for a future per-client limit). A known airport without a report is not a 404 (plan §4).
- **Why:** Plan §3–4 requirements. Live probes on 2026-10-30 showed the real formats: statute-mile visibility including "6+"/"10+", "VRB" wind, an obsTime that differs from reportTime, and garbled reports. The design critique (CORMORANT case 2) found the missing error contract, the missing validity rules, the cache JSON crash and the missing Compose settings; all are fixed.
- **Alternatives considered:** Parse `rawOb` ourselves (more precise visibility, but fragile); cache raw provider responses (re-parsed on every read, and freshness is easy to get wrong); a Redis-shared rate limit (deferred until there's more than one process); 429 for local budget exhaustion (it isn't the client's fault).
- **Source:** CF-003 (issue #4); plan r2 and critique in `~/codex-reviews/clearflight-cf003-design/`.
- **Status:** accepted 2026-10-30 by project owner (plan approval, including the 503 mapping and validity ranges).

### D-005: Airport catalogue is a committed snapshot with timezones derived at import time (2026-10-30)
- **Decision:** Airport metadata comes from OurAirports, filtered to large, medium and small airports with an IATA or ICAO code, and committed as `app/data/airports.csv`. Each airport's IANA zone is derived from its coordinates with `timezonefinder` 9.1.0 / `timezonefinder-data` 4.2026.5 when the snapshot is built (`scripts/import_ourairports.py`), with manual overrides in `app/data/timezone_overrides.csv`. A missing or `Etc/*` zone stays empty, never a fixed offset. The API loads and validates the snapshot at startup and fails to start if it is missing or invalid. DST rules come from the runtime's tz database through `zoneinfo`. Refresh is manual: rerun the script, which validates the new snapshot before replacing the old one.
- **Why:** No runtime or CI dependency on the 30 MB+ boundary data or on the network; reproducible, reviewable data changes; startup failure is better than 500s behind a green health check (owner decision, 2026-10-30). OurAirports + `timezonefinder` was the retained default from RQ-001. A one-off cross-check against OpenFlights (2026-10-30) found the same UTC offsets in January and July for 5,312 of 5,365 shared airports. Of the 53 differences, most come from OpenFlights' stale data (e.g. Yukon, Mexico and Chile rule changes). One was a real lookup error at a border airport, Gold Coast (YBCG), which is now an override.
- **Alternatives considered:** Download at build time (network needed for every build; data changes unreviewed); look up timezones at runtime (heavy dependency in the image); keep AviationStack for metadata (trial access only; returns duplicate records); include heliports, seaplane bases and closed airports (not useful for travellers).
- **Source:** CF-002 (issue #3); plan r2 with CORMORANT critique (`~/codex-reviews/clearflight-cf002-design/`); RQ-001 findings.
- **Status:** accepted 2026-10-30 by project owner (plan approval).

### D-004: Test suite must keep at least 80% coverage, branch-aware (2026-10-19)
- **Decision:** `make check-coverage` (part of `make run-checks`, so also CI) measures `app/` with `--cov-branch` and fails when the total is below 80% (`--cov-fail-under=80`). The total is coverage.py's total with branch measurement on, which counts executed statements and branch outcomes together; it is not a separate branch-only threshold. By review convention, not enforced by the gate, pull requests should not lower total coverage (note before/after in the PR), and exclusions (`# pragma: no cover`) need a stated reason.
- **Why:** Owner's standard for all Python projects. Coverage was reported but never enforced (statement-only: 89% at CF-001 close, 90% later; branch-aware: 91.62% on 2026-10-19, with no partial branches), so a large regression could merge unnoticed. This is a repository-wide floor; the plan §7 pilot gate still applies on top (≥80% for new transformation/scoring logic, with meaningful tests prioritised over the single number).
- **Alternatives considered:** Keep coverage report-only (no protection against regressions); a higher gate (would push towards tests written for the number); a separate branch-only threshold (needs extra tooling; branch coverage is already near 100%).
- **Source:** Owner instruction, 2026-10-19; PR #14.
- **Status:** accepted 2026-10-19 by project owner.

### D-003: Docker Hub publishing only from version tags (2026-10-18)
- **Decision:** CI builds the Docker image without pushing. Publishing happens only in `release.yaml` for `v*` tags, via the `release` GitHub environment.
- **Why:** Avoid publishing images from every push, and gate releases.
- **Source:** PR #11, `docs/cf-001-baseline.md`
- **Status:** accepted. Required reviewer (Yoyo-su) configured on `release` on 2026-10-18.

### D-002: Redis is internal to Docker Compose; hosted Redis via `REDIS_URL` (2026-10-18)
- **Decision:** Do not publish Redis port 6379 on the host. Optional `REDIS_URL` (authenticated `rediss://`) overrides `REDIS_HOST`/`REDIS_PORT`.
- **Why:** Security baseline (plan §3, CF-001.5).
- **Source:** PR #11, `docs/cf-001-baseline.md`
- **Status:** accepted

### D-001: Provider calls use timeouts, status checks and redacted errors (2026-10-18)
- **Decision:** Configurable `PROVIDER_TIMEOUT` (default 10 s). HTTP and provider error bodies are not cached. Access keys are redacted from request errors.
- **Why:** Stable baseline and no credential leakage (CF-001.6).
- **Source:** PR #11, `docs/cf-001-baseline.md`
- **Status:** accepted. Mapping failures to 4xx/5xx is deferred to CF-004.
