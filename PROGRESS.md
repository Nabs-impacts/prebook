# Progression

## Étapes

| Étape | Statut |
| --- | --- |
| 1. Structure du backend | Terminée |
| 2. Modèles base de données | À faire |
| 3. Authentification et rôles | À faire |
| 4. Réglages du site | À faire |
| 5. Catalogue et avis | À faire |
| 6. Upload vidéo | À faire |
| 7. Commandes et paiements | À faire |
| 8. Tatouage PDF et téléchargement sécurisé | À faire |
| 9. Statistiques admin | À faire |
| 10. Optimisation et tests | À faire |

## Décisions prises

- Python 3.12 avec FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL, Redis, ARQ, Pydantic v2 et pydantic-settings.
- Architecture router vers service vers repository.
- Configuration centralisée par variables d'environnement avec `.env` et `.env.example`.
- Logs JSON structurés et request-id propagé dans chaque réponse et chaque erreur.
- Erreurs HTTP renvoyées dans une enveloppe JSON uniforme.
- Images Docker multi-stage et exécution avec un utilisateur non-root.
- Aucun modèle métier créé à cette étape.
- Health check `GET /api/v1/health` vérifiant PostgreSQL et Redis avec retour `503` en cas de dépendance indisponible.
- Tests unitaires et de contrat HTTP avec pytest et pytest-asyncio, sans dépendance à une base réelle.
- Validation effectuée : `ruff check`, `ruff format --check`, `mypy`, `pytest` (7 tests), `alembic current`, build Docker et health check réel sur PostgreSQL et Redis.
- Conteneur API exécuté avec l'utilisateur non-root `prebook` (uid 1001).

## Prochaine étape

Étape 2 : définir les modèles SQLAlchemy et la migration Alembic initiale.
