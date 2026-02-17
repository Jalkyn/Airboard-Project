# Déploiement backend Flask sur Railway

## Fichiers importants
- `Procfile` : commande de lancement (utilise python Windy_Server.py)
- `start.sh` : script de démarrage alternatif
- `Windy_Server.py` : point d'entrée Flask

## Variables d'environnement à configurer sur Railway
- `ALLOWED_ORIGINS` : liste des origines autorisées pour le CORS (ex : https://ton-frontend.vercel.app,https://localhost)
- Toutes les clés API nécessaires à votre application

## Étapes de déploiement
1. Pousser le code sur GitHub
2. Connecter le repo à Railway
3. Configurer les variables d'environnement
4. Déployer

> Par défaut, seul https://localhost est autorisé si ALLOWED_ORIGINS n'est pas défini.
