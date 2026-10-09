.PHONY: up down logs test lint health

up:
	python scripts/init-document-key.py
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	docker compose run --rm api pytest
	docker compose run --rm shipment-service pytest
	docker compose run --rm compliance-service pytest
	docker compose run --rm document-service pytest
	docker compose run --rm intelligence-service pytest

lint:
	ruff check apps/api services packages

health:
	powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1
