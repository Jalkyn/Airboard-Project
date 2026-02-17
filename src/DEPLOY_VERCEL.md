# Déploiement frontend Vite sur Vercel

## Variables d'environnement à configurer sur Vercel
- `VITE_API_URL` : URL publique de l'API backend Railway (ex : https://ton-backend-production.up.railway.app)

## Étapes de déploiement
1. Pousser le code frontend sur GitHub
2. Connecter le repo à Vercel
3. Ajouter la variable d'environnement `VITE_API_URL` dans les settings Vercel
4. Déployer

## Proxy API (optionnel)
Un fichier `vercel.json` permet de réécrire les appels `/api/*` vers l'API backend.
