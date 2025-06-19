########################################
# Makefile for ClearFlight API project #
########################################

PROJECT_NAME = ClearFlight-API
REGION = eu-west-2
PYTHON_INTERPRETER = python
WD=$(shell pwd)
PYTHONPATH=${WD}
IS_CI = $(CI)
SHELL := /bin/bash 
ACTIVATE_ENV := source venv/bin/activate

ifeq ($(IS_CI),true)
	PIP := pip
	BANDIT := bandit
	BLACK := black 
	PYTEST := pytest
	FLAKE8 := flake8
	AUDIT := pip-audit
else
	PIP := $(ACTIVATE_ENV) && pip
	BANDIT := $(ACTIVATE_ENV) && bandit
	BLACK := $(ACTIVATE_ENV) && black 
	PYTEST := $(ACTIVATE_ENV) && pytest
	FLAKE8 := $(ACTIVATE_ENV) && flake8
	AUDIT := $(ACTIVATE_ENV) && pip-audit
endif


# Utility to run a command inside the virtual environment
define execute_in_env
	$(ACTIVATE_ENV) && $1
endef
# Create a virtual environment (skip in CI)
create-environment:
ifeq ($(CI),true)
	@echo ">>> Skipping venv creation in CI."
else
	@echo ">>> Creating local virtual environment"
	python -m venv venv
endif
requirements: create-environment
ifeq ($(CI),true)
	$(PIP) install -r requirements.txt
else
	
	$(call execute_in_env, pip install -r requirements.txt)
endif # Dev setup tools: bandit, black, pytest-cov
dev-setup:
ifeq ($(CI),true)
	$(PIP) install bandit black pytest-cov flake8 pip-audit
else
	$(call execute_in_env, pip install bandit black pytest-cov flake8 pip-audit)
endif

## Run security test
security-test:
	$(BANDIT) -lll ./src/*.py ./tests/*.py

## Run the black code check
run-black:
	$(BLACK) ./src ./tests

## Run the unit tests
unit-test:
	$(PYTEST) -vv --ignore=layer/python --ignore=dependencies_db/python

## Run the coverage check
check-coverage:
	$(PYTEST) --cov=src tests/

## Run lint
lint:
	$(FLAKE8) . --max-line-length=150 --exclude=.git,__pycache__,./venv,./layer,./dependencies_db --ignore=E203,W503,E402

## Run audit
audit:
	$(AUDIT)

## Export Bandit report to JSON
bandit-report:
	mkdir -p reports
	$(BANDIT) -r ./src ./tests -f json -o reports/bandit_report.json


## Run all checks
run-checks: security-test run-black lint unit-test check-coverage audit