# Docker Deployment Guide

TradeTwin is packaged for local project evaluation with Docker Compose.

## Prerequisites

- Docker Desktop with Linux containers enabled.
- WSL 2 integration enabled on Windows.
- Ports `3000`, `8000`, `8011`, `8012`, `8013`, `8014`, `5432`, `6379`,
  `7474`, `7687`, `9000`, and `9001` available.

## Start

```powershell
cd "C:\Users\Rithvik Kumar\Desktop\tradetwin"
docker compose up -d --build
```

## Health Check

```powershell
powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1
```

## Logs

```powershell
docker compose logs -f
```

## Stop

```powershell
docker compose down
```

## Reset Local Data

This removes PostgreSQL, Neo4j, Redis, and MinIO volumes.

```powershell
docker compose down -v
docker compose up -d --build
```

## Local Credentials

Neo4j:

- URL: `http://localhost:7474`
- Username: `neo4j`
- Password: `123456789`

MinIO:

- URL: `http://localhost:9001`
- Username: `tradetwin-local`
- Password: `123456789`

Demo auth tokens are configured in `.env.example`. For a stricter demo, copy
`.env.example` to `.env`, set `AUTH_REQUIRED=true`, and replace all demo tokens.
