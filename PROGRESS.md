# Progression

## Étapes

| Étape | Statut |
| --- | --- |
| 1. Structure du backend | Terminée |
| 2. Modèles base de données | Terminée |
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
- Health check `GET /api/v1/health` vérifiant PostgreSQL et Redis avec retour `503` en cas de dépendance indisponible.
- Tests unitaires et de contrat HTTP avec pytest et pytest-asyncio, sans dépendance à une base réelle.
- Validation effectuée : `ruff check`, `ruff format --check`, `mypy`, `pytest` (7 tests), `alembic current`, build Docker et health check réel sur PostgreSQL et Redis.
- Conteneur API exécuté avec l'utilisateur non-root `prebook` (uid 1001).
- Modèles créés : `User`, `Ebook`, `Order`, `Review`, `SiteSetting`, `DownloadToken`, `WatermarkedFile` et `PageView`.
- Identifiants UUID générés côté Python, horodatages timezone-aware avec valeurs par défaut côté PostgreSQL.
- Enums PostgreSQL natifs `user_role` et `order_status` stockés avec leurs valeurs métier, supprimés explicitement au downgrade.
- `SiteSetting.value` stocké en JSONB et `SiteSetting.key` utilisé comme clé primaire.
- Index composites pour le catalogue publié, les commandes par utilisateur, ebook, statut et date, les avis approuvés par ebook, et les statistiques de pages vues.
- Contraintes de clés étrangères : suppression d'un utilisateur met `orders.user_id` à NULL, suppression d'un ebook est restreinte si des commandes existent, avis et fichiers liés à une commande supprimés en cascade.
- Contrainte d'unicité sur `provider` et `provider_reference` pour l'idempotence des paiements.
- Relations SQLAlchemy en `lazy="raise"` pour empêcher les chargements implicites et les N+1.
- Migration initiale `6d13fbe94f4d` appliquée, vérifiée en upgrade, downgrade puis upgrade, et validée par `alembic check`.

## Prochaine étape

Étape 3 : authentification et rôles, avec hashing des mots de passe, jetons JWT et dépendances d'autorisation.
