# 🚀 Guide de Déploiement du Backend Flask

**⚠️ IMPORTANT** : Vercel ne peut **PAS** exécuter un serveur Flask qui doit tourner en continu. Le backend Flask doit être déployé séparément sur une plateforme qui supporte les applications Python long-running.

## 📋 Plateformes Recommandées

### Option 1 : Railway (Recommandé) ⭐
- ✅ Gratuit avec crédits généreux
- ✅ Déploiement automatique depuis GitHub
- ✅ Configuration simple
- ✅ Support Python natif

### Option 2 : Render
- ✅ Plan gratuit disponible
- ✅ Déploiement automatique depuis GitHub
- ✅ Configuration simple

### Option 3 : Heroku
- ⚠️ Plus de plan gratuit (payant uniquement)
- ✅ Très populaire et bien documenté

---

## 🚂 Déploiement sur Railway

### Étape 1 : Créer un Compte Railway

1. Allez sur [railway.app](https://railway.app)
2. Cliquez sur "Start a New Project"
3. Connectez votre compte GitHub

### Étape 2 : Créer un Nouveau Projet

1. Cliquez sur "New Project"
2. Sélectionnez "Deploy from GitHub repo"
3. Choisissez votre repository : `Jalkyn_Airboard_Project`
4. Railway détectera automatiquement que c'est un projet Python

### Étape 3 : Configurer le Déploiement

1. **Définir le Root Directory** :
   - Cliquez sur votre service
   - Allez dans "Settings"
   - Dans "Source", définissez le **Root Directory** : `Info Windy`
   - Cela indique à Railway où se trouve votre application Flask

2. **Configurer les Variables d'Environnement** :
   - Allez dans "Variables"
   - Ajoutez toutes vos clés API :
     ```
     CEREBRAS_API_KEY=votre_cle_ici
     CEREBRAS_GPT_OSS_120B_KEY=votre_cle_ici
     CEREBRAS_QWEN_235B_KEY=votre_cle_ici
     CEREBRAS_QWEN_32B_KEY=votre_cle_ici
     CEREBRAS_ENDPOINT=https://api.cerebras.ai/v1/completions
     GEMINI_API_KEY=votre_cle_ici
     ```
   - **PORT** et **HOST** sont automatiquement définis par Railway (ne pas les modifier)

3. **Configurer le Build** :
   - Railway détectera automatiquement `requirements.txt`
   - Le fichier `railway.json` configure le démarrage automatique

### Étape 4 : Déployer

1. Railway commencera automatiquement à construire et déployer
2. Attendez que le build se termine (peut prendre 5-10 minutes la première fois)
3. Une fois déployé, Railway vous donnera une URL (ex: `https://your-app.railway.app`)

### Étape 5 : Obtenir l'URL du Backend

1. Dans votre projet Railway, cliquez sur votre service
2. Allez dans "Settings" → "Networking"
3. Copiez l'URL générée (ex: `https://windy-backend.railway.app`)

### Étape 6 : Mettre à Jour Vercel

1. Allez sur votre projet Vercel
2. Allez dans "Settings" → "Environment Variables"
3. Mettez à jour `VITE_API_URL` avec l'URL Railway :
   ```
   VITE_API_URL=https://windy-backend.railway.app
   ```
4. Redéployez votre frontend Vercel

---

## 🎨 Déploiement sur Render

### Étape 1 : Créer un Compte Render

1. Allez sur [render.com](https://render.com)
2. Créez un compte (gratuit)
3. Connectez votre compte GitHub

### Étape 2 : Créer un Nouveau Web Service

1. Cliquez sur "New +" → "Web Service"
2. Sélectionnez votre repository : `Jalkyn_Airboard_Project`
3. Render détectera automatiquement la configuration depuis `render.yaml`

### Étape 3 : Configurer le Service

1. **Nom du service** : `windy-flask-backend`
2. **Root Directory** : `Info Windy`
3. **Build Command** : `pip install -r requirements.txt`
4. **Start Command** : `python Windy_Server.py`
5. **Python Version** : `3.11.0`

### Étape 4 : Ajouter les Variables d'Environnement

Dans la section "Environment Variables", ajoutez :
```
CEREBRAS_API_KEY=votre_cle_ici
CEREBRAS_GPT_OSS_120B_KEY=votre_cle_ici
CEREBRAS_QWEN_235B_KEY=votre_cle_ici
CEREBRAS_QWEN_32B_KEY=votre_cle_ici
CEREBRAS_ENDPOINT=https://api.cerebras.ai/v1/completions
GEMINI_API_KEY=votre_cle_ici
```

### Étape 5 : Déployer

1. Cliquez sur "Create Web Service"
2. Render commencera le build automatiquement
3. Attendez la fin du déploiement (5-10 minutes)
4. Votre backend sera disponible sur `https://windy-flask-backend.onrender.com`

### Étape 6 : Mettre à Jour Vercel

1. Allez sur votre projet Vercel
2. Mettez à jour `VITE_API_URL` avec l'URL Render
3. Redéployez votre frontend

---

## 🔧 Configuration CORS

Le backend est déjà configuré pour accepter les requêtes depuis n'importe quelle origine. Si vous voulez restreindre aux domaines spécifiques, modifiez `Windy_Server.py` :

```python
CORS(app, resources={
    r"/*": {
        "origins": [
            "https://your-frontend.vercel.app",
            "http://localhost:3000"  # Pour le développement local
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Cache-Control"],
        "supports_credentials": True
    }
})
```

---

## 🐛 Dépannage

### Le Build Échoue

**Problème** : Erreur lors de l'installation des dépendances

**Solutions** :
1. Vérifiez que `requirements.txt` est dans le dossier `Info Windy`
2. Vérifiez que toutes les dépendances sont listées
3. Pour Railway, vérifiez les logs de build dans le dashboard
4. Pour Render, vérifiez les logs dans la section "Logs"

### Le Serveur Ne Démarre Pas

**Problème** : Le service démarre mais crash immédiatement

**Solutions** :
1. Vérifiez les logs dans Railway/Render
2. Vérifiez que `Windy_Server.py` est le bon fichier de démarrage
3. Vérifiez que le PORT est bien utilisé (Railway/Render le définissent automatiquement)
4. Vérifiez que toutes les variables d'environnement sont définies

### Erreur 502 Bad Gateway

**Problème** : Le backend ne répond pas

**Solutions** :
1. Vérifiez que le service est bien déployé et en cours d'exécution
2. Vérifiez les logs pour voir les erreurs
3. Vérifiez que l'URL est correcte dans Vercel
4. Testez l'endpoint `/api/health` directement dans votre navigateur

### Les Requêtes CORS Échouent

**Problème** : Le frontend ne peut pas communiquer avec le backend

**Solutions** :
1. Vérifiez que CORS est bien configuré dans `Windy_Server.py`
2. Vérifiez que l'URL du backend est correcte dans `VITE_API_URL`
3. Vérifiez les logs du backend pour voir les erreurs CORS

---

## 📝 Fichiers de Configuration Créés

Les fichiers suivants ont été créés pour faciliter le déploiement :

- **`Info Windy/Procfile`** : Pour Heroku/Railway
- **`Info Windy/runtime.txt`** : Version Python
- **`Info Windy/railway.json`** : Configuration Railway
- **`Info Windy/render.yaml`** : Configuration Render

---

## ✅ Checklist de Déploiement

- [ ] Backend déployé sur Railway/Render
- [ ] Variables d'environnement configurées (clés API)
- [ ] Backend accessible via URL publique
- [ ] Test de `/api/health` fonctionne
- [ ] `VITE_API_URL` mis à jour dans Vercel
- [ ] Frontend Vercel redéployé
- [ ] Test de connexion frontend → backend réussi

---

## 🎉 Une Fois Déployé

Votre architecture complète sera :

```
Frontend (Vercel)
    ↓ HTTPS
Backend Flask (Railway/Render)
    ↓ API Calls
Cerebras API, Gemini API, etc.
```

Le frontend sur Vercel communiquera avec le backend sur Railway/Render via HTTPS.

---

## 📚 Ressources

- [Railway Documentation](https://docs.railway.app)
- [Render Documentation](https://render.com/docs)
- [Flask Deployment Guide](https://flask.palletsprojects.com/en/latest/deploying/)
