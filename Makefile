PYTHON ?= .venv/bin/python
.PHONY: install db-up db-test-up migrate demo api-run web-run test coverage lint type openapi check web-check
install:
	uv sync --locked --all-extras
db-up:
	docker compose -p review_platform_oss up -d postgres
db-test-up:
	docker compose -p review_platform_oss up -d --wait --wait-timeout 60 postgres-test
migrate:
	$(PYTHON) -m alembic upgrade head
demo:
	$(PYTHON) -m review_platform.dev_seed
api-run:
	$(PYTHON) -m uvicorn review_platform.main:create_app --factory --host 127.0.0.1 --port 8780
web-run:
	npm --prefix apps/web run dev
test: db-test-up
	$(PYTHON) scripts/run_tests.py
coverage: db-test-up
	$(PYTHON) scripts/run_tests.py --cov=review_platform --cov-report=term-missing
lint:
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .
type:
	$(PYTHON) -m mypy
openapi:
	$(PYTHON) scripts/generate_openapi.py --check
	$(PYTHON) -m openapi_spec_validator packages/contracts/openapi/openapi-v1.json
web-check:
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck
	npm --prefix apps/web run format:check
	npm --prefix apps/web run openapi:check
	npm --prefix apps/web test
	npm --prefix apps/web run build
check: lint type openapi coverage web-check
