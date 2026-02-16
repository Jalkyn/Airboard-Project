# 🚀 Déploiement du Backend Flask

Ce dossier contient le serveur Flask backend qui doit être déployé séparément du frontend.

## ⚠️ IMPORTANT

**Vercel ne peut PAS exécuter un serveur Flask.** Le backend doit être déployé sur :
- Railway (recommandé)
- Render
- Heroku
- Ou toute autre plateforme supportant Python

## 📋 Fichiers de Configuration

- **`Procfile`** : Pour Railway/Heroku
- **`runtime.txt`** : Version Python
- **`railway.json`** : Configuration Railway
- **`render.yaml`** : Configuration Render
- **`requirements.txt`** : Dépendances Python

## 🚀 Déploiement Rapide

### Sur Railway (Recommandé)

1. Allez sur [railway.app](https://railway.app)
2. Créez un nouveau projet depuis GitHub
3. Définissez le **Root Directory** : `Info Windy`
4. Ajoutez les variables d'environnement (clés API)
5. Railway déploiera automatiquement

### Sur Render

1. Allez sur [render.com](https://render.com)
2. Créez un nouveau Web Service depuis GitHub
3. Le fichier `render.yaml` sera détecté automatiquement
4. Ajoutez les variables d'environnement
5. Déployez

## 📖 Documentation Complète

Voir [BACKEND_DEPLOYMENT.md](../BACKEND_DEPLOYMENT.md) pour le guide complet.

## 🔧 Variables d'Environnement Requises

```
CEREBRAS_API_KEY=votre_cle
CEREBRAS_GPT_OSS_120B_KEY=votre_cle
CEREBRAS_QWEN_235B_KEY=votre_cle
CEREBRAS_QWEN_32B_KEY=votre_cle
CEREBRAS_ENDPOINT=https://api.cerebras.ai/v1/completions
GEMINI_API_KEY=votre_cle
```

**Note** : `PORT` et `HOST` sont automatiquement définis par la plateforme de déploiement.
