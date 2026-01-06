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
git commit -m "Initial commit"
git push -u origin main
```

2. Create a new Web Service on Render:
   - Connect your GitHub repository
   - Build Command: `npm install && npm run build`
   - Start Command: `npm run preview` (or use a static site service)
   - For static site: Set Publish Directory to `dist`

3. Set Environment Variables in Render:
   - `VITE_BASE44_APP_ID`: Your Base44 App ID

4. Configure Base44 Integrations:
   - **Gmail Integration**: Connect order@korealy email account
   - **Shopify Integration**: Connect your Shopify store

## Environment Variables

See `.env.example` for all required environment variables.

### Required Base44 Functions

The following Base44 functions must be configured in your Base44 dashboard:

1. `fetchKorealyEmails` - Fetches shipping emails from Gmail
2. `processKorealyShippingREST` - Updates Shopify orders with tracking numbers

### Base44 Integrations Setup

**Gmail Integration:**
- Email: order@korealy
- Scopes: `gmail.readonly`
- Used to fetch Korealy shipping notification emails

**Shopify Integration:**
- Store URL: your-store.myshopify.com
- Permissions: `write_orders`, `read_orders`
- Used to update order fulfillments with tracking numbers