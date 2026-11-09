ENV_FILE := $(if $(wildcard .env),--env-file .env)

.PHONY: sync format lint test openapi client check-generated verify e2e dev worker migrate seed

sync:
	uv sync --locked

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy

test:
	uv run pytest --cov

openapi:
	DATABASE_URL= uv run api-fastapi-starter openapi > openapi.json

client: openapi
	uv run openapi-python-client generate --path openapi.json --output-path clients/python/api_client \
		--overwrite --config clients/config.yaml --meta none

check-generated: client
	git diff --exit-code -- openapi.json clients/python

verify: lint check-generated test
	scripts/check-migrations.sh
	.agents/check.sh
	.github/scripts/check-repo-standards.sh

e2e:
	uv run pytest tests/e2e

dev:
	uv run $(ENV_FILE) uvicorn app.asgi:app --reload --port 3000

worker:
	uv run $(ENV_FILE) api-fastapi-starter worker

migrate:
	uv run $(ENV_FILE) api-fastapi-starter migrate

seed:
	uv run $(ENV_FILE) api-fastapi-starter seed
