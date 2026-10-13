# Docker Deployment Guide

Existing commercial data requires the [Phase 4 backup and rollback procedure](guarded-dispatch-phase4.md#setup-and-migration).
Do not remove persistent volumes when deploying the upgrade.

TradeTwin is packaged for local project evaluation with Docker Compose.

## Prerequisites

- Docker Desktop with Linux containers enabled.
- WSL 2 integration enabled on Windows.
- Ports `3000`, `8000`, `8011`, `8012`, `8013`, `8014`, `5432`, `6379`,
  `7474`, `7687`, `9000`, and `9001` available.

## Start

```powershell
cd "C:\Users\Rithvik Kumar\Desktop\tradetwin"
python scripts/init-document-key.py
docker compose up -d --build
```

## Health Check

```powershell
powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1 -GuardedDispatch
```

The setup script creates missing credentials without replacing an existing encryption
keyring. On Windows it restricts newly created secret files to the local owner, SYSTEM,
and Administrators so Docker Desktop can mount them. Never delete a keyring to resolve
a startup error. Keep backup archives out of Git and Docker build contexts.

The Phase 4 health option checks endpoint registration and denies unauthenticated
registry access; it does not simulate a legal approval. Also check `docker compose ps`
for the document worker and ClamAV. See the [Phase 4 verification report](phase4-deployment-verification.md)
for tested paths and remaining production limitations.

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
