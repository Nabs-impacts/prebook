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

## Premier super administrateur

```bash
cd backend
SUPER_ADMIN_EMAIL=admin@example.com SUPER_ADMIN_PASSWORD='MotDePasseSolide123!' \
  uv run python -m app.cli create-super-admin
```

Les options `--email` et `--password` sont aussi acceptées. Aucun identifiant n'est stocké dans le code.

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
- `ACCESS_TOKEN_TTL_MINUTES`
- `REFRESH_TOKEN_TTL_DAYS`
- `LOGIN_RATE_LIMIT_ATTEMPTS`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `PASSWORD_MIN_LENGTH`
- `SUPER_ADMIN_EMAIL`
- `SUPER_ADMIN_PASSWORD`

## Authentification

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Les jetons d'accès durent 15 minutes et les jetons de rafraîchissement 7 jours, avec rotation et révocation stockée dans Redis. Le login est limité à 5 tentatives par minute et par couple IP/email.

## Administration

Les routes `/api/v1/admin/admins` sont réservées au rôle `super_admin` :

- `GET` : liste paginée
- `POST` : création d'un administrateur
- `PATCH /{id}` : activation, désactivation ou changement de mot de passe
- `DELETE /{id}` : suppression

Chaque opération et chaque login administrateur alimente la table `admin_audit_logs`.

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
