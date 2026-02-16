# ✅ Configuration Backend Flask pour Déploiement

## 📋 Problème Résolu

**Problème** : Vercel ne peut pas exécuter un serveur Flask qui doit tourner en continu.

**Solution** : Le backend Flask doit être déployé séparément sur Railway ou Render.

## 🔧 Modifications Effectuées

### 1. Fichiers de Configuration Créés

- ✅ **`Info Windy/Procfile`** - Pour Railway/Heroku
- ✅ **`Info Windy/runtime.txt`** - Version Python (3.11.0)
- ✅ **`Info Windy/railway.json`** - Configuration Railway
- ✅ **`Info Windy/render.yaml`** - Configuration Render
- ✅ **`Info Windy/README_DEPLOYMENT.md`** - Guide rapide

### 2. Modifications du Code

- ✅ **`Windy_Server.py`** :
  - Utilise maintenant `HOST` et `PORT` depuis les variables d'environnement
  - Supporte le mode debug via `FLASK_DEBUG`
  - CORS configuré pour accepter les requêtes depuis Vercel
  - Compatible avec Railway/Render qui définissent automatiquement PORT

- ✅ **`requirements.txt`** :
  - Ajout de `python-dotenv>=1.0.0` (déjà présent mais maintenant explicitement listé)

### 3. Documentation

- ✅ **`BACKEND_DEPLOYMENT.md`** - Guide complet de déploiement
- ✅ **`VERCEL_DEPLOYMENT.md`** - Mis à jour avec avertissement sur l'architecture

## 🚀 Prochaines Étapes

### 1. Déployer le Backend sur Railway (Recommandé)

1. Allez sur [railway.app](https://railway.app)
2. Créez un nouveau projet depuis GitHub
3. **Root Directory** : `Info Windy`
4. Ajoutez les variables d'environnement (clés API)
5. Railway déploiera automatiquement

### 2. Obtenir l'URL du Backend

Une fois déployé, Railway vous donnera une URL comme :
```
https://your-backend.railway.app
```

### 3. Mettre à Jour Vercel

1. Allez sur votre projet Vercel
2. Settings → Environment Variables
3. Mettez à jour `VITE_API_URL` avec l'URL Railway
4. Redéployez

## 📝 Variables d'Environnement Requises (Backend)

Dans Railway/Render, ajoutez :

```
CEREBRAS_API_KEY=votre_cle
CEREBRAS_GPT_OSS_120B_KEY=votre_cle
CEREBRAS_QWEN_235B_KEY=votre_cle
CEREBRAS_QWEN_32B_KEY=votre_cle
CEREBRAS_ENDPOINT=https://api.cerebras.ai/v1/completions
GEMINI_API_KEY=votre_cle
```

**Note** : `PORT` et `HOST` sont automatiquement définis par la plateforme.

## 🔗 Architecture Finale

```
┌─────────────────┐
│  Frontend React │
│     (Vercel)    │
└────────┬────────┘
         │ HTTPS
         │ VITE_API_URL
         ▼
┌─────────────────┐
│  Backend Flask  │
│ (Railway/Render)│
└────────┬────────┘
         │ API Calls
         ▼
┌─────────────────┐
│  Cerebras API   │
│   Gemini API    │
└─────────────────┘
```

## 📚 Documentation

- Guide complet : [BACKEND_DEPLOYMENT.md](./BACKEND_DEPLOYMENT.md)
- Guide Vercel : [VERCEL_DEPLOYMENT.md](./VERCEL_DEPLOYMENT.md)
