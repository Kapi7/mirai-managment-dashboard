# Quick Start Guide

Get your independent Mirai Dashboard running in 3 steps!

## Prerequisites

- Node.js 18+ installed
- Gmail account (that receives emails from order@korealy)
- Shopify store with Admin API access

## Step 1: Gmail OAuth Setup (15 minutes)

This is the most important step. Follow [GMAIL_SETUP.md](./GMAIL_SETUP.md) carefully to:

1. Create Google Cloud project
2. Enable Gmail API
3. Create OAuth credentials
4. Get refresh token via OAuth Playground

You'll get:
- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

## Step 2: Configure Environment

Copy the example file:
```bash
cp .env.example .env
```

Edit `.env` and fill in:
```env
# Frontend
VITE_API_URL=http://localhost:3001

# Shopify (you already have these)
SHOPIFY_STORE=9dkd2w-g3.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx_your_token_here

# Gmail (from Step 1)
GMAIL_CLIENT_ID=your_client_id_here
GMAIL_CLIENT_SECRET=your_client_secret_here
GMAIL_REFRESH_TOKEN=your_refresh_token_here
GMAIL_REDIRECT_URI=http://localhost:3001/auth/google/callback
GMAIL_USER_EMAIL=your_support_email@gmail.com
```

## Step 3: Run the App

### Terminal 1 - Start Backend
```bash
cd server
npm install
npm start
```

You should see:
```
🚀 Mirai Backend running on port 3001
```

Test it:
```bash
curl http://localhost:3001/health
```

Should return: `{"status":"ok","timestamp":"..."}`

### Terminal 2 - Start Frontend
```bash
# From project root
npm install
npm run dev
```

Visit: **http://localhost:5173**

## Testing the Integration

1. Open http://localhost:5173 in your browser
2. Click **"Refresh"** button
3. Should see emails from order@korealy
4. Click **"Update"** on any pending order
5. Check Shopify - tracking should be added!

## Troubleshooting

### Backend won't start
```bash
cd server
npm install
node index.js
```
Check error messages for missing env variables

### "Failed to fetch emails"
- Verify Gmail credentials in `.env`
- Check that Gmail API is enabled in Google Cloud
- Make sure refresh token is valid (regenerate if needed)

### "Failed to add tracking"
- Verify Shopify store URL (should include .myshopify.com)
- Check Shopify access token is correct
- Ensure token has `write_orders` permission

### No emails showing up
- Make sure your Gmail account actually receives emails from order@korealy
- Try searching Gmail directly for: `from:order@korealy subject:shipped`
- Check server logs for errors

### Frontend can't connect to backend
- Make sure backend is running on port 3001
- Check `VITE_API_URL` in `.env` is set to `http://localhost:3001`
- Try accessing http://localhost:3001/health directly

## Next: Deploy to Production

Once everything works locally, follow [RENDER_DEPLOYMENT.md](./RENDER_DEPLOYMENT.md) to deploy!

## Need Help?

1. Check server logs in Terminal 1
2. Check browser console (F12) for frontend errors
3. Review [GMAIL_SETUP.md](./GMAIL_SETUP.md) for Gmail issues
4. Verify all `.env` variables are filled in correctly
