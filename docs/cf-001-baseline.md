# CF-001 — Recovery baseline

Initial commit on main: `2657bec4663cbcb33ae22f669fa03d5b7925fa91` (23 September 2025).

Last recorded CI run: [Clearflight-CI/CD — success](https://github.com/Yoyo-su/ClearFlight-API/actions/runs/17956224746). This is a historical result, **not** evidence of a successful October 2026 run.

## Known baseline issues

- README uses a query-style airport endpoint, but `app/main.py` implements `GET /airport/{airport_code}`.
- Airport time calculation uses fixed GMT offsets, not IANA timezones or DST.
- Provider calls have no explicit timeout or HTTP-status validation.
- Cache keys hash URLs containing API access keys (no key is printed but URLs should not include secrets).
- `weather_risk_calc` is heuristic; not suitable for operational claims.
- Former Compose file published Redis port 6379 to the host.
- Existing CI publishes a Docker Hub image automatically but does not deploy an app.
- Airport response lacks Pydantic response validation.

## Reproduction checks

From the repository root:

```sh
cp .env.template .env
# add your development API keys to .env
docker compose up --build
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/airport/EGLL
docker compose exec clearflightapi pytest -q
```

The airport lookup requires functional provider credentials. A local Docker build and full pytest run still require verification.

## CF-001 remaining

### Dependency remediation verification — 18 October 2026

Updated vulnerable application pins, including urllib3 2.8.0 and a compatible
FastAPI 0.143.3 / Starlette 1.3.1 pair. `make dev-setup` now installs the pinned
tools in `requirements-dev.txt`, including patched pip and setuptools.

Verified locally on Python 3.13.1 in a fresh virtual environment, installed with
`python -m pip install -r requirements.txt -r requirements-dev.txt`:

- `python -m pip check`: no broken requirements.
- `pip-audit`: no known vulnerabilities found (no advisory exclusions).
- `pytest --cov=app tests/ -q` with dummy provider keys: 50 passed; 87% coverage.
- Black check, Makefile lint and security checks: passed in the development environment.

Service tests now mock Redis as well as provider HTTP calls. Routing regression
tests cover IATA and ICAO lookups. Starlette emits a deprecation warning for the
existing httpx test client integration; tests pass. No live provider calls,
Docker build, hosted deployment or new GitHub Actions result were verified here.
Audit results are time-specific; keep the CI audit enabled.

### Hardening verification — 18 October 2026

Branch `pilot/cf-001-hardening`, from `main` at `7d51986`.

- Provider calls use a configurable `PROVIDER_TIMEOUT` (default 10 s), check the
  HTTP status, reject error bodies from 200 responses, and never cache failed
  responses. A missing cache key no longer raises `UnboundLocalError`. The
  `/airport/{airport_code}` success response is unchanged.
- Optional `REDIS_URL` (for example an authenticated `rediss://` URL) overrides
  `REDIS_HOST`/`REDIS_PORT`. Local Compose is unchanged.
- `make run-black` is now a non-mutating `black --check` (`make format` reformats).
  `make security-test` scans `app/` and `tests/` recursively at medium severity
  and above; the previous run missed `requests` calls without timeouts (B113).
- CI uses dummy provider keys and builds the Docker image without pushing on
  pushes and pull requests. Docker Hub publishing moved to `release.yaml`
  (version tags or manual run, `release` environment).
- Dockerfile base image pinned to `python:3.13-slim`. The unpinned `python:3-slim` caused the
  failed Docker build on `main` (run 39094696865): it resolved to a newer Python
  with no `pydantic_core` 2.33.2 wheel, and the source build had no compiler.

Verified locally (Python 3.13.1 venv, Docker 28.2.2, Compose v2.36.2), with
dummy provider keys:

- `make run-checks`: bandit, black check, flake8, 63 tests passed, 89% coverage,
  `pip-audit` found no known vulnerabilities.
- `docker compose build` and `docker compose up -d`: `GET /` returned
  `{"status":"ok"}`; the API container reached Redis; Redis was not reachable
  from the host (connection refused on 127.0.0.1:6379); only
  `127.0.0.1:8000` was published.
- `pytest` inside the container (Python 3.13.16): 63 passed.

Review fixes (PR #11):

- Provider request errors are redacted before they are printed, logged or
  raised. Requests puts the full URL, including `access_key`, in HTTP error,
  connection error and connect-timeout messages; the connection-error leak
  predated this branch. The original exception is suppressed from tracebacks.
- Docker Compose now passes the optional `REDIS_URL` to the API container
  (verified: set, the client uses TLS to the hosted address; unset, it uses the
  internal `redis` service).
- `release.yaml` publishes only when run for a `v*` tag; branch names are not
  valid image tags.
- `make run-checks`: 70 tests passed, 89% coverage, no known vulnerabilities.

Not verified here: a GitHub Actions run of the release workflow, live provider
lookups (`/airport/EGLL`) and a hosted Redis connection.

- [x] Rebuild Docker on a developer machine or CI, recording exact results (local; CI run pending).
- [x] Confirm tests, lint, dependency vulnerability audit and response handling.
- [x] Update HTTP timeouts and errors while preserving existing response shape.
- [x] Move Docker Hub publishing to a separately gated release workflow.
- [x] Finalise an opt-in hosted `REDIS_URL` with authenticated TLS (hosted connection verified in CF-006).
- [x] Fix README setup/endpoint mismatch.

Deferred to CF-004: mapping provider failures to 400/404/502/504 responses, and
removing API access keys from the URLs hashed into cache keys.
