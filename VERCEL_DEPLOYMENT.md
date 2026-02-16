# 🚀 Vercel Deployment Guide

This guide will help you deploy the AirBoard frontend to Vercel and configure it securely with your own API keys.

## ⚠️ IMPORTANT : Architecture de Déploiement

**Vercel ne peut PAS exécuter un serveur Flask qui doit tourner en continu.**

Votre application doit être déployée en **2 parties séparées** :

1. **Frontend React** → Déployé sur **Vercel** (ce guide)
2. **Backend Flask** → Déployé sur **Railway** ou **Render** (voir [BACKEND_DEPLOYMENT.md](./BACKEND_DEPLOYMENT.md))

## 📋 Prerequisites

1. **GitHub Account** - Your project is already on GitHub (`Jalkyn_Airboard_Project`)
2. **Vercel Account** - Sign up at [vercel.com](https://vercel.com) (free tier available)
3. **Backend API** - Your Flask backend **MUST** be deployed separately first (Railway, Render, Heroku, etc.)
   - ⚠️ **IMPORTANT** : Déployez d'abord le backend avant de configurer Vercel
   - Voir [BACKEND_DEPLOYMENT.md](./BACKEND_DEPLOYMENT.md) pour les instructions complètes

## 🔐 Security: API Keys Configuration

**⚠️ IMPORTANT**: This project is configured so that **users must enter their own API keys**. No API keys are hardcoded in the source code.

### Frontend Environment Variables

The frontend only needs the backend API URL. API keys are handled by the backend.

### Backend Environment Variables

Your backend (Flask server) needs these API keys. Configure them in your backend deployment platform:

- `CEREBRAS_API_KEY` - Cerebras API key (generic)
- `CEREBRAS_GPT_OSS_120B_KEY` - For GPT-OSS-120B model
- `CEREBRAS_QWEN_235B_KEY` - For Qwen-3-235B model
- `CEREBRAS_QWEN_32B_KEY` - For Llama-3.3-70B model
- `CEREBRAS_ENDPOINT` - Cerebras API endpoint (default: `https://api.cerebras.ai/v1/completions`)
- `GEMINI_API_KEY` - Google Gemini API key

## 📦 Step-by-Step Deployment

### Step 1: Prepare Your Repository

1. **Ensure `.env` is in `.gitignore`** (already configured ✅)
   - Your `.env` file should never be committed
   - Only `.env.example` should be in the repository

2. **Verify your project structure**:
   ```
   Windy_Project_Airboard/
   ├── src/
   ├── package.json
   ├── vite.config.ts
   ├── vercel.json ✅
   └── .env.example ✅
   ```

### Step 2: Deploy to Vercel

#### Option A: Deploy via Vercel Dashboard (Recommended)

1. **Go to [vercel.com](https://vercel.com)** and sign in
2. **Click "Add New Project"**
3. **Import your GitHub repository** (`Jalkyn_Airboard_Project`)
4. **Configure the project**:
   - **Framework Preset**: Vite (should auto-detect)
   - **Root Directory**: `./` (root of repository)
   - **Build Command**: `npm run build` (auto-filled)
   - **Output Directory**: `dist` (auto-filled)
   - **Install Command**: `npm install` (auto-filled)

5. **Add Environment Variables**:
   - Click "Environment Variables"
   - Add the following:
     ```
     VITE_API_URL = https://your-backend-url.com
     ```
   - Replace `https://your-backend-url.com` with your actual backend API URL
   - Select environments: Production, Preview, Development

6. **Click "Deploy"**

#### Option B: Deploy via Vercel CLI

1. **Install Vercel CLI**:
   ```bash
   npm i -g vercel
   ```

2. **Login to Vercel**:
   ```bash
   vercel login
   ```

3. **Deploy**:
   ```bash
   vercel
   ```

4. **Set environment variables**:
   ```bash
   vercel env add VITE_API_URL
   # Enter your backend URL when prompted
   ```

5. **Deploy to production**:
   ```bash
   vercel --prod
   ```

### Step 3: Configure Backend Deployment

Your Flask backend needs to be deployed separately. Here are recommended platforms:

#### Option 1: Railway
1. Go to [railway.app](https://railway.app)
2. Create a new project from GitHub
3. Add environment variables in Railway dashboard
4. Deploy your Flask backend
5. Copy the Railway URL and use it as `VITE_API_URL` in Vercel

#### Option 2: Render
1. Go to [render.com](https://render.com)
2. Create a new Web Service
3. Connect your GitHub repository
4. Set build command: `pip install -r requirements.txt`
5. Set start command: `python "Info Windy/Windy_Server.py"`
6. Add environment variables
7. Copy the Render URL and use it as `VITE_API_URL` in Vercel

#### Option 3: Heroku
1. Install Heroku CLI
2. Create a new app: `heroku create your-app-name`
3. Set environment variables: `heroku config:set CEREBRAS_API_KEY=your_key`
4. Deploy: `git push heroku main`
5. Use the Heroku URL as `VITE_API_URL` in Vercel

### Step 4: Update Environment Variables

After deploying your backend:

1. **Get your backend URL** (e.g., `https://your-backend.railway.app`)
2. **Update Vercel environment variables**:
   - Go to Vercel Dashboard → Your Project → Settings → Environment Variables
   - Update `VITE_API_URL` with your backend URL
   - Redeploy if necessary

## 🔧 Configuration Files

### `vercel.json`
This file configures Vercel deployment:
- Build command: `npm run build`
- Output directory: `dist`
- Framework: Vite
- SPA routing: All routes redirect to `index.html`

### `.env.example`
Template file showing required environment variables. Users should:
1. Copy to `.env` for local development
2. Configure in Vercel dashboard for production

### `src/lib/api-config.ts`
Centralized API configuration that:
- Reads `VITE_API_URL` from environment variables
- Defaults to `http://localhost:5000` for local development
- Provides helper functions for API calls

## 🧪 Testing Your Deployment

1. **Check build logs** in Vercel dashboard
2. **Visit your deployed site** (e.g., `https://your-project.vercel.app`)
3. **Test API connectivity**:
   - Open browser console
   - Check for API errors
   - Verify backend URL is correct

## 🔄 Updating Your Deployment

### Automatic Deployments
- **Production**: Deploys automatically when you push to `main` branch
- **Preview**: Creates preview deployments for pull requests

### Manual Updates
1. Push changes to GitHub
2. Vercel automatically detects changes
3. New deployment starts automatically
4. You'll get a notification when deployment completes

## 🐛 Troubleshooting

### Build Fails
- Check build logs in Vercel dashboard
- Verify `package.json` has correct scripts
- Ensure all dependencies are listed in `package.json`

### API Calls Fail
- Verify `VITE_API_URL` is set correctly in Vercel
- Check CORS settings on your backend
- Ensure backend is accessible from the internet
- Check browser console for specific error messages

### Environment Variables Not Working
- Ensure variables start with `VITE_` prefix
- Redeploy after adding/changing environment variables
- Check variable names match exactly (case-sensitive)

### Routing Issues (404 on refresh)
- `vercel.json` already includes SPA routing configuration
- If issues persist, check that `vercel.json` is in the root directory

## 📝 Important Notes

1. **API Keys Security**:
   - ✅ API keys are stored in backend environment variables
   - ✅ Frontend never sees API keys
   - ✅ Each user must configure their own backend with their own API keys
   - ✅ `.env` file is gitignored

2. **Backend CORS**:
   Make sure your Flask backend allows requests from your Vercel domain:
   ```python
   from flask_cors import CORS
   CORS(app, resources={r"/api/*": {"origins": ["https://your-project.vercel.app"]}})
   ```

3. **Environment Variables**:
   - Frontend: Only `VITE_API_URL` is needed
   - Backend: All API keys (Cerebras, Gemini, etc.)

## 🎉 Success!

Once deployed, your application will be available at:
- **Production**: `https://your-project.vercel.app`
- **Preview**: `https://your-project-git-branch.vercel.app`

Share this URL with users, and they can configure their own backend with their own API keys!

## 📚 Additional Resources

- [Vercel Documentation](https://vercel.com/docs)
- [Vite Deployment Guide](https://vitejs.dev/guide/static-deploy.html)
- [Environment Variables in Vercel](https://vercel.com/docs/concepts/projects/environment-variables)
