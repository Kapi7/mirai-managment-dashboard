# Render Deployment Guide

## Step 1: Push to GitHub

```bash
git add .
git commit -m "Initial commit: Mirai Management Dashboard"
git push -u origin main
```

## Step 2: Create Render Web Service

1. Go to [Render Dashboard](https://dashboard.render.com/)
2. Click **"New +" → "Web Service"**
3. Connect your GitHub account and select repository: `Kapi7/mirai-managment-dashboard`

## Step 3: Configure Service Settings

### Basic Settings:
- **Name**: `mirai-management-dashboard`
- **Region**: Choose closest to you
- **Branch**: `main`
- **Root Directory**: Leave empty
- **Runtime**: `Node`

### Build & Deploy:
- **Build Command**: `npm install && npm run build`
- **Start Command**: `npm run preview`

### Plan:
- **Instance Type**: Free (or Starter for production)

## Step 4: Environment Variables

Click **"Advanced" → "Add Environment Variable"**

Add:
```
VITE_BASE44_APP_ID=691afeab306bf144680a5668
```

## Step 5: Deploy

Click **"Create Web Service"**

Render will:
1. Clone your repo
2. Run `npm install && npm run build`
3. Start the server with `npx vite preview`
4. Give you a live URL like: `https://mirai-management-dashboard.onrender.com`

## Step 6: Configure Base44 Integrations

Go to your [Base44 Dashboard](https://base44.com/dashboard):

### Gmail Integration:
1. Navigate to Integrations → Add Gmail
2. Authenticate with: **order@korealy**
3. Grant permission: `gmail.readonly`

### Shopify Integration:
1. Navigate to Integrations → Add Shopify
2. Store URL: `9dkd2w-g3.myshopify.com`
3. Access Token: `shpat_xxxxx...` (use your Shopify Admin API token)
4. Permissions: `write_orders`, `read_orders`

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
