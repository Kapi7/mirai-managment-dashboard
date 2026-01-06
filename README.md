# Mirai Management Dashboard

Independent admin dashboard for Mirai Skin business operations. Built with React (frontend) + Node.js/Express (backend).

## Features

- **Korealy Tracking**: Automatically sync shipping emails from order@korealy with Shopify orders
- **Direct Gmail Integration**: No third-party services required
- **Direct Shopify Integration**: Update tracking numbers via Shopify Admin API

## Architecture

```
Frontend (React + Vite) ← → Backend (Node.js + Express) ← → Gmail API + Shopify API
```

## Setup

### 1. Gmail API Setup

Follow the detailed guide in [GMAIL_SETUP.md](./GMAIL_SETUP.md) to:
- Create Google Cloud project
- Enable Gmail API
- Get OAuth credentials
- Generate refresh token

### 2. Install Dependencies

**Frontend:**
```bash
npm install
```

**Backend:**
```bash
cd server
npm install
```

### 3. Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

Required variables:
- `SHOPIFY_STORE` - Your Shopify store URL
- `SHOPIFY_ACCESS_TOKEN` - Shopify Admin API token
- `GMAIL_CLIENT_ID` - From Google Cloud Console
- `GMAIL_CLIENT_SECRET` - From Google Cloud Console
- `GMAIL_REFRESH_TOKEN` - From OAuth flow (see GMAIL_SETUP.md)

### 4. Run Development Servers

**Backend:**
```bash
cd server
npm start
```

**Frontend** (in another terminal):
```bash
npm run dev
```

Visit `http://localhost:5173`

**Quick Start:** See [QUICK_START.md](./QUICK_START.md) for a step-by-step guide!

## Building for Production

**Frontend:**
```bash
npm run build
```

**Backend:**
Backend runs directly with Node.js (no build step required)

## Deployment to Render

1. Push your code to GitHub:
```bash
git add .
git commit -m "Deploy to production"
git push origin main
```

2. Create a Web Service on Render:
   - Connect your GitHub repository: `Kapi7/mirai-managment-dashboard`
   - **Build Command:** `./build.sh`
   - **Start Command:** `./start.sh`
   - Root Directory: (leave empty)

3. Set Environment Variables in Render:
   ```
   SHOPIFY_STORE=your-store.myshopify.com
   SHOPIFY_ACCESS_TOKEN=your_shopify_token
   GMAIL_CLIENT_ID=your_gmail_client_id
   GMAIL_CLIENT_SECRET=your_gmail_client_secret
   GMAIL_REFRESH_TOKEN=your_gmail_refresh_token
   GMAIL_REDIRECT_URI=https://your-app.onrender.com/auth/google/callback
   GMAIL_USER_EMAIL=your_support_email@gmail.com
   ```

4. Deploy and visit your URL!

## Environment Variables

### Local Development (.env file)
```env
VITE_API_URL=http://localhost:3001

SHOPIFY_STORE=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxx

GMAIL_CLIENT_ID=xxxxx
GMAIL_CLIENT_SECRET=xxxxx
GMAIL_REFRESH_TOKEN=xxxxx
GMAIL_REDIRECT_URI=http://localhost:3001/auth/google/callback
GMAIL_USER_EMAIL=your_email@gmail.com
```

### Gmail API Setup

Follow [GMAIL_SETUP.md](./GMAIL_SETUP.md) for detailed instructions on:
- Creating Google Cloud project
- Enabling Gmail API
- Getting OAuth credentials
- Generating refresh token

### Shopify API Setup

1. Go to Shopify Admin → Settings → Apps and sales channels
2. Click "Develop apps" → "Create an app"
3. Configure Admin API scopes: `write_orders`, `read_orders`
4. Install app and copy the Admin API access token