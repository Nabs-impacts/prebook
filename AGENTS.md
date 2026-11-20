# AGENTS

Au début de chaque session, lire `CONTEXT.md` et `PROGRESS.md`.

## Règles absolues

- Aucun commentaire dans le code, aucune docstring.
- Code async et typé strictement.
- Les routers délèguent aux services, les services aux repositories.
- Requêtes optimisées : pas de N+1, index adaptés, pagination, cache Redis pour les lectures fréquentes.

## Fin de tâche

Mettre à jour `PROGRESS.md` (statut des étapes, décisions prises, prochaine étape) avant de rendre le travail.
