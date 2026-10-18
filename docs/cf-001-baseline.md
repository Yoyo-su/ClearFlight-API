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

- [ ] Rebuild Docker on a developer machine or CI, recording exact results.
- [ ] Confirm tests, lint, dependency vulnerability audit and response handling.
- [ ] Update HTTP timeouts and errors while preserving existing response shape.
- [ ] Move Docker Hub publishing to a separately gated release workflow.
- [ ] Finalise an opt-in hosted `REDIS_URL` with authenticated TLS.
- [ ] Fix README setup/endpoint mismatch.
