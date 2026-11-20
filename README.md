# Prebook

Backend d'un site e-commerce d'ebooks pour un créateur de contenu.

## Stack

- Python 3.12
- FastAPI et Pydantic v2
- SQLAlchemy 2.0 async et Alembic
- PostgreSQL et Redis
- ARQ
- Docker, uv, ruff, pytest, pre-commit

## Prérequis

- Python 3.12
- uv
- Docker et Docker Compose

## Installation

```bash
cp .env.example .env
cd backend
uv sync --python 3.12
```

## Lancement avec Docker

```bash
docker compose up --build -d
```

L'API est disponible sur `http://localhost:8000` et la documentation sur `http://localhost:8000/docs`.

## Lancement en local

Démarrer PostgreSQL et Redis :

```bash
docker compose up -d postgres redis
```

Lancer l'API depuis `backend/` :

```bash
uv run uvicorn app.main:app --reload --port 8010
```

## Migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
```

## Worker ARQ

```bash
cd backend
uv run arq app.tasks.worker.WorkerSettings
```

## Tests et qualité

```bash
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
pre-commit install
pre-commit run --all-files
```

## Health check

```bash
curl http://localhost:8000/api/v1/health
```

La réponse contient le statut de PostgreSQL et de Redis. Le service renvoie `503` si une dépendance est indisponible.

## Configuration

Les variables d'environnement sont définies dans `.env` :

- `APP_NAME`
- `ENV`
- `SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `CORS_ORIGINS`
- `LOG_LEVEL`

## Structure

```text
backend/
  app/
    api/v1/
    core/
    db/
    models/
    repositories/
    schemas/
    services/
    tasks/
  alembic/
  tests/
```
