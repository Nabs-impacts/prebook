# Contexte du projet Prebook

## Produit

Site e-commerce d'ebooks pour un créateur de contenu. Le backend expose une API FastAPI consommée par un frontend React. Le site doit être très rapide et optimisé pour le référencement et la conversion.

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2.0 en mode async
- Alembic
- PostgreSQL
- Redis
- ARQ
- Pydantic v2 et pydantic-settings
- Docker et docker-compose
- pytest, pytest-asyncio, ruff, mypy, pre-commit

## Règles absolues

- Aucun commentaire dans le code, aucune docstring.
- Tout le code est async et typé strictement.
- Aucune logique métier dans les routers : routers vers services, services vers repositories.
- Optimisation des requêtes : pas de N+1, index adaptés, pagination systématique, cache Redis pour les données lues souvent.

## Architecture

```text
backend/
  app/
    main.py
    core/
      config.py
      security.py
      deps.py
      logging.py
      errors.py
      middleware.py
    db/
      session.py
      base.py
    models/
    schemas/
    api/
      v1/
        router.py
        endpoints/
    services/
    repositories/
    tasks/
  tests/
  alembic/
```

Le flux applicatif est router vers service vers repository. Les repositories possèdent les accès base de données, les services portent la logique métier et les routers se limitent à la validation et à la sérialisation HTTP.

## Fonctionnalités prévues

- DRM social avec tatouage numérique dynamique des PDF par acheteur.
- Panel admin avec statistiques de ventes et de visites.
- Super admin pouvant ajouter et supprimer des administrateurs.
- Affichage du nombre d'avis et du nombre d'achats activable ou désactivable depuis l'admin.
- Mode maintenance configurable.
- Vidéo de présentation uploadable via Cloudflare R2 ou Stream avec upload direct par URL présignée.
- Paiements Mynita, Amanata et Wave derrière une interface PaymentProvider, l'agrégateur étant choisi plus tard.
- Site très optimisé, avec cache Redis et requêtes SQL maîtrisées.

## Étapes

1. Structure du backend
2. Modèles base de données
3. Authentification et rôles
4. Réglages du site
5. Catalogue et avis
6. Upload vidéo
7. Commandes et paiements
8. Tatouage PDF et téléchargement sécurisé
9. Statistiques admin
10. Optimisation et tests
