# ClearFlight-API
An API which provides real-time traffic & weather information for airports, routings and flight numbers.


## Architecture

![Airport API](https://github.com/user-attachments/assets/26de1a9b-385f-4478-91de-c6a7f3f01761)


## Endpoints
### GET /airport - Implementation in progress

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

4. Check the docker-compose.yml file to ensure the configuration is correct. If you need to make changes, do so before building the image.

5. Configure environment variables if necessary. You can create a `.env` file in the project root to manage sensitive information. Use the `.env.template` as a guide.

6. Build and run the Docker container:
   ```bash
   docker-compose up --build
   ```

7. Access the API at `http://localhost:8000`. Status should be `ok` if everything is set up correctly.

8. To stop the container, use:
   ```bash
   docker-compose down
   ```

## Future Features
- Visual dashboard
- AI Advisor (GPT)
- Predictive weather and traffic (ML)

