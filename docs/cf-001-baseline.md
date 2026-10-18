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

- [ ] Rebuild Docker on a developer machine or CI, recording exact results.
- [ ] Confirm tests, lint, dependency vulnerability audit and response handling.
- [ ] Update HTTP timeouts and errors while preserving existing response shape.
- [ ] Move Docker Hub publishing to a separately gated release workflow.
- [ ] Finalise an opt-in hosted `REDIS_URL` with authenticated TLS.
- [ ] Fix README setup/endpoint mismatch.
