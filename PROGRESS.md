# Progression

## Étapes

| Étape | Statut |
| --- | --- |
| 1. Structure du backend | Terminée |
| 2. Modèles base de données | Terminée |
| 3. Authentification et rôles | Terminée |
| 4. Réglages du site | Terminée |
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
- Mots de passe hachés avec Argon2 (`argon2-cffi`) et vérification sans révéler l'existence d'un compte.
- JWT signés HS256 : access token de 15 minutes, refresh token de 7 jours avec `jti` et type de jeton. Les refresh tokens sont stockés hachés (SHA-256) dans Redis et consommés atomiquement pour la rotation.
- Révocation des refresh tokens par utilisateur lors d'une désactivation, d'un changement de mot de passe ou d'une suppression. Le logout révoque aussi le `jti` de l'access token jusqu'à son expiration.
- Rate limiting du login dans Redis : 5 tentatives par minute par couple IP/email, réponse `429` au-delà.
- Dépendances `require_admin` et `require_super_admin` basées sur l'utilisateur rechargé depuis la base, afin de prendre en compte immédiatement les désactivations et changements de rôle.
- Règles métier appliquées côté service : auto-suppression et auto-désactivation interdites, dernier super administrateur actif protégé, gestion des administrateurs réservée au super administrateur.
- Table `admin_audit_logs` alimentée à chaque login réussi et à chaque création, modification ou suppression d'administrateur. `admin_id` est mis à NULL à la suppression de l'acteur, `target_id` reste conservé sans clé étrangère.
- Migration `c3a9e5f7b2d1` appliquée et validée par `alembic upgrade`, `alembic downgrade -1`, `alembic upgrade head` et `alembic check`.
- CLI `python -m app.cli create-super-admin` avec email et mot de passe lus depuis `--email`/`--password` ou `SUPER_ADMIN_EMAIL`/`SUPER_ADMIN_PASSWORD`, testée sur PostgreSQL.
- Tests pytest portés à 28 : login réussi et échoué, message générique, compte inactif, rate limiting, rotation et réutilisation des refresh tokens, logout, rôles et permissions, auto-suppression, dernier super administrateur, pagination, audit et révocation après changement de mot de passe.
- Validation finale : `ruff check`, `ruff format --check`, `mypy app tests`, `pytest` (28 tests), `alembic check`.
- Réglages du site stockés dans `site_settings` (JSONB) avec schéma Pydantic strict `extra="forbid"` et valeurs par défaut : `maintenance_mode`, `maintenance_message`, `show_reviews_count`, `show_purchases_count`.
- `SettingsService` lit d'abord Redis (`settings:site`, TTL 300 s), puis charge tous les réglages en une seule requête SQL et met le résultat complet en cache. Chaque modification invalide puis réécrit le cache.
- Les mises à jour partielles utilisent un `INSERT ... ON CONFLICT DO UPDATE` groupé et refusent les clés inconnues, les valeurs nulles et les payloads vides.
- `GET /api/v1/public/settings` renvoie les quatre réglages publics avec `Cache-Control: public, max-age=30` et un `ETag` fort, avec réponse `304` sur `If-None-Match`.
- `GET` et `PATCH /api/v1/admin/settings` sont protégés par `require_admin` et chaque clé modifiée crée une entrée `admin_audit_logs` avec `target_key`, `old_value` et `new_value`.
- Migration `d7b2f4a9c1e6` ajoutant `target_key`, `old_value`, `new_value` à `admin_audit_logs` et la valeur d'enum `settings_updated`.
- Middleware de maintenance : réponse `503` JSON avec message configurable et `Retry-After`, sauf pour `/api/v1/health`, `/api/v1/auth/*`, `/api/v1/admin/*` et `/api/v1/public/settings`. Le middleware lit les réglages via le service et le cache Redis, sans requête SQL directe.
- Helper `SettingsService.resolve_optional_counts` pour les futurs endpoints catalogue : les compteurs désactivés renvoient `None` sans exécuter leur requête de comptage.
- Tests pytest portés à 38 : valeurs par défaut, mise à jour partielle, clés inconnues et payload vide, cache et invalidation, ETag, maintenance et routes exemptées, droits d'accès et audit des réglages.
- Validation finale de l'étape 4 : `ruff format`, `ruff check`, `mypy app tests`, `pytest` (38 tests), `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` et `alembic check`.

## Prochaine étape

Étape 5 : catalogue et avis, en réutilisant `SettingsService.resolve_optional_counts` pour masquer les compteurs désactivés.
