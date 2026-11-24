# Progression

## Étapes

| Étape | Statut |
| --- | --- |
| 1. Structure du backend | Terminée |
| 2. Modèles base de données | Terminée |
| 3. Authentification et rôles | Terminée |
| 4. Réglages du site | Terminée |
| 5. Catalogue et avis | Terminée |
| 6. Upload vidéo | Terminée |
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
- Catalogue public exposé sous `/api/v1/ebooks` : liste paginée avec champs légers (`summary`), détail complet avec note moyenne calculée par sous-requête SQL agrégée, et avis approuvés paginés.
- Colonnes `summary` et `deleted_at` ajoutées à `ebooks`, avec index `ix_ebooks_is_published_deleted_at_created_at` et `ix_orders_ebook_id_status` via la migration `e5c1a7b3d902`.
- Slug généré automatiquement à la création à partir du titre, translittéré en ASCII et rendu unique par suffixe numérique ; il reste stable lors d'une modification de titre pour préserver les URLs.
- Les compteurs `reviews_count` et `purchases_count` passent par `resolve_optional_counts` : désactivés, ils valent `null` sans aucune requête de comptage. Pour les listes, les compteurs manquants sont calculés par agrégation groupée `IN (...)` puis mis en cache, ce qui évite tout N+1.
- Compteurs stockés séparément dans Redis par ebook (`catalog:counter:reviews:*`, `catalog:counter:purchases:*`, TTL 600 s) et invalidés lors de l'approbation ou de la suppression d'un avis, avec un hook `on_order_paid` prêt pour l'étape commandes.
- Réponses publiques de liste, détail et avis mises en cache Redis avec version de catalogue (`catalog:version`) incrémentée à chaque modification admin, approbation ou suppression d'avis. Les clés incluent les drapeaux d'affichage des compteurs.
- `ETag` fort et `Cache-Control: public, max-age=60` sur les GET publics, avec `304` sur `If-None-Match`. `SettingsService.resolve_optional_counts` accepte désormais des réglages déjà chargés pour éviter des lectures Redis répétées.
- Avis publics créés avec `is_approved = false`, validation stricte Pydantic, suppression itérative des balises HTML et échappement des caractères restants. Rate limiting Redis par IP (`3` dépôts par heure par défaut, configurables).
- Administration du catalogue sous `/api/v1/admin/ebooks` : création, modification, publication, dépublication et suppression. La publication exige une couverture et un PDF ; la suppression est logique si des commandes existent.
- Interface `StorageBackend` avec implémentation `LocalStorageBackend` : PDF dans un dossier privé non monté, couvertures dans un dossier public servi sous `/media`. Ajout de `python-multipart`, d'un volume Docker `storage_data` et des limites de taille configurables.
- Modération sous `/api/v1/admin/reviews` : liste filtrée `pending`/`approved`/`all`, approbation et suppression. Les changements approuvés invalident compteurs et caches publics.
- Tests pytest portés à 50 : liste/détail, brouillon invisible, création et modération d'avis, XSS, rate limiting, compteurs actifs/désactivés sans requête, cache et invalidation, droits admin, slugs uniques, uploads, suppression logique et pagination.
- Validation finale de l'étape 5 : `ruff check`, `ruff format --check`, `mypy app tests`, `pytest` (50 tests), `alembic upgrade head` et `alembic check` sur PostgreSQL temporaire. Les plans `EXPLAIN` confirment l'usage des index de catalogue, d'avis approuvés et de commandes payées.

- Stockage R2 ajouté via `aioboto3` : `R2StorageBackend` expose l'API S3 compatible, est sélectionné par `STORAGE_BACKEND=local|r2` et conserve les PDF privés. Les couvertures utilisent `R2_PUBLIC_BASE_URL`, les PDF passent par une URL présignée de courte durée (`PRESIGNED_URL_TTL_SECONDS`, 300 s par défaut).
- Variables R2 et Cloudflare Stream ajoutées à la configuration et à `.env.example`, avec limites d'upload vidéo configurables (`VIDEO_MAX_DURATION_SECONDS`, `VIDEO_MAX_SIZE_BYTES`).
- Modèle `Video` avec enums natifs `video_provider` et `video_status`, index sur `ebook_id`, `(provider, provider_video_id)` et `status`. `Ebook.preview_video_id` devient une clé étrangère UUID vers `videos.id` avec `ON DELETE SET NULL`, ce qui garantit au plus une vidéo active par ebook.
- Migration `f8a2c4d6e910` appliquée, testée en upgrade, downgrade puis upgrade sur PostgreSQL temporaire et validée par `alembic check`.
- Interface `VideoProvider` avec `CloudflareStreamProvider` (httpx async, direct creator upload, synchronisation, suppression) et `ExternalUrlProvider` (validation YouTube/Vimeo et génération du lien embed).
- Endpoints admin : création d'URL d'upload direct, attachement d'une vidéo externe, synchronisation manuelle du statut et détachement avec suppression distante. Le remplacement conserve l'ancienne vidéo active jusqu'à ce que la nouvelle soit `ready`, puis bascule le pointeur et supprime l'ancienne.
- Webhook `POST /api/v1/webhooks/cloudflare-stream` avec vérification HMAC SHA-256 du header `Webhook-Signature`, mise à jour du statut, de la durée, de la miniature et du flux HLS, invalidation du cache catalogue et exemption du mode maintenance. Le traitement est idempotent, y compris pour les rejeux et les vidéos inconnues.
- Le détail public renvoie un objet `video` (`provider`, `hls_url`, `thumbnail_url`, `duration_seconds`, `embed_url`) uniquement lorsque le statut est `ready`, sans aucun appel Cloudflare : tout provient de PostgreSQL et du cache Redis.
- Tests pytest portés à 63 : upload direct, webhook valide/invalide/rejoué, exemption maintenance, refresh, remplacement, suppression distante, vidéos externes valides et invalides, visibilité publique selon le statut, droits admin et backend R2 mocké (upload, suppression, URL présignée, sélection).
- Validation finale de l'étape 6 : `ruff format --check`, `ruff check`, `mypy app tests`, `pytest` (63 tests), migrations sur PostgreSQL temporaire et aller-retour ORM `Ebook`/`Video`.

## Prochaine étape

Étape 7 : commandes et paiements derrière l'interface `PaymentProvider`.
