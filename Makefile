# Shortcuts for the commands used daily. Executable documentation: a README
# telling someone to run `docker compose up -d --build` goes out of date, a
# target in here does not.
#
# Run `make` with no arguments to list what is available.

.DEFAULT_GOAL := help
.PHONY: help up down logs ps test lint fmt build demo scale clean status

## help: show this list
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## /  /'

## up: build and start the whole environment
up:
	docker compose up -d --build

## demo: start the environment with three vessels reporting
demo:
	docker compose up -d --build --scale agent=3

## scale: change the number of agents, e.g. make scale N=5
scale:
	docker compose up -d --scale agent=$(N)

## down: stop everything, keeping recorded data
down:
	docker compose down

## clean: stop everything and delete the database volume
clean:
	docker compose down -v

## logs: follow the logs of every service
logs:
	docker compose logs -f

## ps: show what is running and whether it is healthy
ps:
	docker compose ps

## status: print the current fleet summary
status:
	@curl -s http://localhost:8000/api/fleet/status

## test: run the test suite
test:
	pytest -v

## lint: check style and common errors
lint:
	ruff check app/ agent/

## fmt: reformat the code
fmt:
	ruff format app/ agent/

## build: build the images without starting anything
build:
	docker compose build
