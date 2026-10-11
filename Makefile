.PHONY: up down logs test test-backend test-web lint health

up:
	python scripts/init-document-key.py
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test: test-backend test-web

test-backend:
	docker compose run --build --rm --no-deps api pytest --import-mode=importlib
	docker compose run --build --rm --no-deps shipment-service pytest --import-mode=importlib
	docker compose run --build --rm --no-deps compliance-service pytest --import-mode=importlib
	docker compose run --build --rm --no-deps document-service pytest --import-mode=importlib
	docker compose run --build --rm --no-deps intelligence-service pytest --import-mode=importlib

test-web:
	docker compose run --build --rm --no-deps web-test

lint:
	ruff check apps/api services packages scripts conftest.py
	python scripts/check-architecture.py
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck
	npm --prefix apps/web run check:architecture

health:
	powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1
