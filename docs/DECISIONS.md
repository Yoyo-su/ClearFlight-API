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

### D-004: Test suite must keep at least 80% branch coverage (2026-10-19)
- **Decision:** `make check-coverage` (part of `make run-checks`, so also CI) measures `app/` with branch coverage and fails below 80% (`--cov-fail-under=80`). Pull requests should not lower total coverage, and exclusions (`# pragma: no cover`) need a stated reason.
- **Why:** Owner's standard for all Python projects. Coverage was reported but never enforced (89% at CF-001 close, 92% branch coverage on 2026-10-19), so a regression could merge unnoticed.
- **Alternatives considered:** Keep coverage report-only (no protection against regressions); a higher gate (would push towards tests written for the number).
- **Consequence:** This is a repository-wide floor. The plan §7 pilot gate still applies on top: ≥80% for new transformation/scoring logic, with meaningful tests prioritised over the single number.
- **Source:** Owner instruction, 2026-10-19.
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
