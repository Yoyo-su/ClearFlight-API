# ClearFlight-API
An API which provides real-time traffic & weather information for airports, routings and flight numbers.


## Architecture

![Airport API](https://github.com/user-attachments/assets/e697753b-2f7a-42d4-9bd0-607756f326f8)


## Endpoints
### GET /airport
Fetches airport metadata and weather information from the existing prototype providers. Live airport traffic is not yet implemented.

example: `/airport/KJFK` or `/airport/JFK` (legacy prototype route; `/v1/airports/{code}/conditions` is planned for the pilot) 

<img width="386" height="629" alt="image" src="https://github.com/user-attachments/assets/c66bc2e2-2396-4c6a-ba16-ba8f4a1a2b04" />


### GET /route - To be implemented

### GET /flight - To be implemented



## 🚀 Setup & Deployment

This project uses GitHub Actions for continuous integration and deployment, the workflow automatically runs tests and checks. 

The CI/CD pipeline is triggered on:
  - Pushes to the main branch

### Continuous Integration  
The run-tests job performs the following steps:

 - Configures the Python environment and installs dependancies
 - Runs python security, format and linting checks
 - Runs pytests and checks test coverage

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

## Future Features
- Visual dashboard
- AI Advisor (GPT)
- Predictive weather and traffic (ML)


## Pilot development

See [Development Plan v1.0](docs/development-plan.md) and [CF-001 recovery baseline](docs/cf-001-baseline.md). The pilot adds a traveller-facing airport weather dashboard, but is not yet publicly deployed.
