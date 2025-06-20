# ClearFlight-API
An API which provides real-time and historical traffic & weather information for airports, routings and flight numbers.



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

4. Build the Docker image:
   ```bash
   docker build -t clearflight-api .
   ```

5. Run the Docker container:
   ```bash
   docker run --name clearflight -p 8000:8000 clearflight-api
   ```

6. Access the API at `http://localhost:8000`. Status should be `ok` if everything is set up correctly.

