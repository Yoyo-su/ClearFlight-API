# ClearFlight-API
An API which provides real-time traffic & weather information for airports, routings and flight numbers.


## Architecture

![Airport API](https://github.com/user-attachments/assets/e697753b-2f7a-42d4-9bd0-607756f326f8)


## Endpoints
### GET /airport
Fetches airport metadata and weather information from the existing prototype providers. Live airport traffic is not yet implemented.

example: `/airport/KJFK` or `/airport/JFK` (legacy prototype route; `/v1/airports/{code}/conditions` is planned for the pilot) 

<img width="386" height="629" alt="image" src="https://github.com/user-attachments/assets/c66bc2e2-2396-4c6a-ba16-ba8f4a1a2b04" />


### GET /v1/airports/search
Searches the local airport catalogue (OurAirports data, no provider call) by IATA or ICAO code, name or city. Matching ignores case and accents.

Parameters: `q` (2–64 characters, required), `limit` (1–25, default 10).

example: `/v1/airports/search?q=heathrow` returns
```json
{
  "query": "heathrow",
  "count": 1,
  "results": [
    {
      "code": "EGLL", "icao": "EGLL", "iata": "LHR",
      "name": "London Heathrow Airport", "city": "London",
      "country": "United Kingdom", "country_code": "GB",
      "type": "large_airport", "timezone": "Europe/London",
      "latitude": 51.470748, "longitude": -0.459909
    }
  ]
}
```
- Results are ordered: exact IATA/ICAO code, then name or city starting with `q`, then a word starting with `q`, then any other match; ties go to larger airports, then by name.
- `code` is the ICAO code, or the IATA code when the airport has no ICAO code. `icao`, `iata`, `city`, `country` and `timezone` can be `null`.
- `timezone` is an IANA zone ID. A few remote airports have none (`null`); the API never substitutes a fixed offset.
- No match returns `200` with an empty `results` list. A missing, too short or too long `q`, or an invalid `limit`, returns `400`.

The catalogue covers large, medium and small airports with an IATA or ICAO code (about 11,000). It is a committed snapshot in `app/data/airports.csv`; see [Updating the airport catalogue](#updating-the-airport-catalogue).

### GET /route - To be implemented

### GET /flight - To be implemented



## 🚀 Setup & Deployment

This project uses GitHub Actions for continuous integration and deployment, the workflow automatically runs tests and checks. 

The CI pipeline (`CF_deploy.yaml`) is triggered on:
  - Pushes to `main` and `pilot/**` branches
  - Pull requests into `main`

### Continuous Integration  
The run-tests job performs the following steps:

 - Configures the Python environment and installs dependencies
 - Runs python security, format (`black --check`) and linting checks
 - Runs pytests and enforces at least 80% test coverage (branch-aware)
 - Audits dependencies for known vulnerabilities

The docker-build job then builds the Docker image without publishing it. Tests mock all provider calls, so CI uses dummy API keys.

### Release
Publishing the Docker Hub image is handled separately by `release.yaml`, which publishes only for version tags (`v*`; a manual run must be started on such a tag), repeats the checks and uses the `release` GitHub environment.

### Local Setup
Docker is used to run the API. To set it up, follow these steps:

1. Ensure you have Docker installed on your machine. If not, you can download it from [Docker's official website](https://www.docker.com/get-started).

2. Clone the repository to your local machine:
   ```bash
   git clone https://github.com/Yoyo-su/ClearFlight-API.git
   ```

3. Navigate to the project directory:
   ```bash
   cd ClearFlight-API
   ```

4. Copy `.env.template` to `.env` and add your own API credentials. Inside Docker Compose Redis is reachable as `redis` (not `localhost`).

5. Keep `.env` private. Do not commit API keys. Redis is internal to Docker Compose; only the API is bound to `127.0.0.1:8000`.

6. Build and run the Docker container:
   ```bash
   docker compose up --build
   ```

7. Access the API at `http://localhost:8000`. Status should be `ok` if everything is set up correctly.

8. To stop the container, use:
   ```bash
   docker compose down
   ```

### Running the checks locally
`make run-checks` runs the same checks as CI (bandit, black, flake8, pytest, the coverage gate and pip-audit). It needs Python 3.13 available as `python`.

```bash
make requirements dev-setup   # creates ./venv and installs dependencies
export PYTHONPATH=$PWD        # lets the tests import the app package, as CI does
export AVIATIONSTACK_API_KEY=ci-dummy-key WEATHERSTACK_API_KEY=ci-dummy-key
make run-checks
```

The tests mock the providers, so dummy keys are enough, and no real credentials are needed. Without the keys (or a `.env`), test collection fails with a settings validation error. Without `PYTHONPATH`, it fails with `ModuleNotFoundError: No module named 'app'`. If the project directory is moved, recreate `venv` (`rm -rf venv && make requirements dev-setup`), because a virtual environment's paths are fixed when it is created.

### Updating the airport catalogue
`app/data/airports.csv` is built from [OurAirports](https://ourairports.com/data/) by `scripts/import_ourairports.py`, which also derives each airport's IANA timezone from its coordinates with `timezonefinder`. The script and its dependencies are not needed to run the API or the tests. To refresh the snapshot:
```bash
python -m venv .venv-import && .venv-import/bin/pip install -r requirements.txt -r requirements-import.txt
.venv-import/bin/python scripts/import_ourairports.py
```
The new snapshot is validated first (codes, coordinates, timezone IDs, the three pilot airports, and a row count within 10% of the current one; pass `--allow-size-change` to accept a bigger change). If validation fails, the current files are left unchanged. `app/data/airports.meta.json` records the source, date, library versions and airports without a timezone. To correct an airport's timezone, add a row to `app/data/timezone_overrides.csv` and rerun the script. Review the diff before committing.

Data sources: airport data from [OurAirports](https://ourairports.com/data/) (public domain); timezone boundaries via [timezonefinder](https://github.com/jannikmi/timezonefinder) (MIT) and [timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder) (ODbL); timezone rules from the [IANA tz database](https://www.iana.org/time-zones).

## Future Features
- Visual dashboard
- AI Advisor (GPT)
- Predictive weather and traffic (ML)


## Pilot development

See [Development Plan v1.0](docs/development-plan.md) and [CF-001 recovery baseline](docs/cf-001-baseline.md). The pilot adds a traveller-facing airport weather dashboard, but is not yet publicly deployed.
