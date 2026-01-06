# Render Deployment Guide

This app requires deploying **two services**: Backend (Node.js API) and Frontend (Static Site).

## Step 1: Push to GitHub

```bash
git add .
git commit -m "Independent backend with Gmail and Shopify integration"
git push -u origin main
```

## Step 2: Deploy Backend API

### 2.1 Create Web Service

1. Go to [Render Dashboard](https://dashboard.render.com/)
2. Click **"New +" → "Web Service"**
3. Connect your GitHub account and select repository: `Kapi7/mirai-managment-dashboard`

### 2.2 Configure Backend Settings

**Basic Settings:**
- **Name**: `mirai-backend`
- **Region**: Choose closest to you
- **Branch**: `main`
- **Root Directory**: `server`
- **Runtime**: `Node`

**Build & Deploy:**
- **Build Command**: `npm install`
- **Start Command**: `npm start`

**Instance Type:**
- Free tier OK for testing
- Starter ($7/mo) recommended for production

### 2.3 Environment Variables

Click **"Advanced" → "Add Environment Variable"**

Add these variables:

```
SHOPIFY_STORE=9dkd2w-g3.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx_your_token_here
GMAIL_CLIENT_ID=your_gmail_client_id
GMAIL_CLIENT_SECRET=your_gmail_client_secret
GMAIL_REFRESH_TOKEN=your_gmail_refresh_token
GMAIL_REDIRECT_URI=https://mirai-backend.onrender.com/auth/google/callback
GMAIL_USER_EMAIL=your_support@email.com
```

**Important:**
- Get Gmail credentials from [GMAIL_SETUP.md](./GMAIL_SETUP.md)
- Update `GMAIL_REDIRECT_URI` with your actual Render backend URL
- Add this redirect URI to Google Cloud Console OAuth credentials

### 2.4 Deploy Backend

Click **"Create Web Service"**

You'll get a URL like: `https://mirai-backend.onrender.com`

**Save this URL** - you'll need it for the frontend!

Test it works:
```bash
curl https://mirai-backend.onrender.com/health
```

## Step 3: Deploy Frontend

### 3.1 Create Static Site

1. In Render Dashboard, click **"New +" → "Static Site"**
2. Select same repository: `Kapi7/mirai-managment-dashboard`

### 3.2 Configure Frontend Settings

**Basic Settings:**
- **Name**: `mirai-dashboard`
- **Branch**: `main`
- **Root Directory**: Leave empty

**Build & Deploy:**
- **Build Command**: `npm install && npm run build`
- **Publish Directory**: `dist`

### 3.3 Environment Variables

Add:
```
VITE_API_URL=https://mirai-backend.onrender.com
```

**Replace with your actual backend URL from Step 2.4!**

### 3.4 Deploy Frontend

Click **"Create Static Site"**

You'll get a URL like: `https://mirai-dashboard.onrender.com`

## Step 4: Update Google Cloud OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Navigate to **APIs & Services** → **Credentials**
3. Edit your OAuth 2.0 Client ID
4. Add to **Authorized redirect URIs**:
   ```
   https://mirai-backend.onrender.com/auth/google/callback
   ```
5. Save

## Step 5: Test Production App

Visit your frontend URL: `https://mirai-dashboard.onrender.com`

Click **"Refresh"** to fetch Korealy emails - should work now!

## Troubleshooting

### Build fails?
- Check that `package.json` has all dependencies
- Verify Node version (should be 18+)

### App loads but "Failed to fetch emails"?
- Check Base44 Gmail integration is connected
- Verify `fetchKorealyEmails` function exists in Base44 dashboard

### "Failed to add tracking"?
- Check Base44 Shopify integration is connected
- Verify `processKorealyShippingREST` function exists in Base44 dashboard

## Architecture

```
User Browser
    ↓
Render (React App)
    ↓
Base44 SDK → Base44 Backend Functions
                ↓                ↓
            Gmail API      Shopify API
```

All sensitive credentials (Gmail OAuth, Shopify tokens) are stored in Base44, not in your code.
