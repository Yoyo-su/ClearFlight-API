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
