# ClearFlight — AI Agent Instructions

## Project context
ClearFlight is a traveller-oriented flight and airport information project. The current README documents a Python API, an implemented `GET /airport` endpoint, and `GET /route` and `GET /flight` as not yet implemented. The next pilot is weather-focused; do not assume advanced tracking, prediction, or a frontend already exists.
Prioritize a small, deployable weather pilot with understandable weather information for travellers, reliable data handling and low operating cost (target under £30/month). Development time is roughly 5–10 hours/week.

## General engineering rules
- Read README.md and existing project documentation before proposing changes.
- Inspect the actual repository; distinguish implemented functionality from planned work.
- For substantial changes, propose a short plan and acceptance criteria before editing.
- Work in small, focused increments and follow existing patterns.
- Avoid new dependencies without a clear reason.
- Add or update tests for changed behavior; run relevant checks and report what could not be run.
- Explain assumptions, risks, changed files and outstanding work in the final summary.

## Safety and collaboration
- Never expose, print, commit or hardcode credentials, tokens or private user data.
- Use documented environment-variable configuration and example files without secrets.
- Never deploy, change live infrastructure, delete data, force-push, or run destructive commands without explicit approval.
- Never commit, push or merge changes unless explicitly requested.
- Preserve unrelated edits and avoid rewriting files outside the task.
- Do not claim tests, external APIs or deployments work without verification.
- Prefer approval before running commands that access production systems or incur costs.

## ClearFlight-specific guidance
- Follow the existing Python/FastAPI, Docker and GitHub Actions structure after inspecting the code.
- Preserve existing endpoint contracts unless a change is agreed and documented.
- Treat upstream aviation/weather data as fallible: handle timeouts, invalid data, missing fields, quotas and provider errors gracefully.
- Keep API credentials server-side; never expose provider keys in logs, tests or frontend responses.
- Mock external API calls in automated tests; do not require paid/live API requests for CI.
- Clearly label observed weather versus forecasts; do not fabricate flight status, weather, timestamps or confidence.
- Prefer measurable, weather-focused pilot features over speculative flight-tracking functionality.
- Keep provider costs, rate limits and deployment footprint visible when recommending architecture.

## Validation
- Discover the actual test, formatting, linting and container commands from repository files and CI before running them.
- Test both success and failure paths, especially upstream errors and missing weather data.
- Update API documentation when endpoint behavior or response schemas change.

## Project documents
- `docs/CURRENT_MILESTONE.md`: active milestone, scope, acceptance criteria and next task.
- `docs/ARCHITECTURE.md`: current versus planned structure.
- `docs/DECISIONS.md`: recorded decisions; do not contradict them without flagging it.

## Review mode
When asked to review (for example by Codex), do not modify files or git state. Compare the branch with `main` against `docs/CURRENT_MILESTONE.md`, and report findings by severity (Critical/High/Medium/Low) with `path:line` references, evidence and the checks actually run.
