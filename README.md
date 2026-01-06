# Mirai Management Dashboard

Admin dashboard for Mirai Skin business operations. Built with React, Vite, and Base44 for backend operations.

## Features

- **Korealy Tracking**: Sync shipping emails from Korealy with Shopify orders

## Setup

1. Install dependencies:
```bash
npm install
```

2. Create a `.env` file with required environment variables (see `.env.example`)

3. Run the development server:
```bash
npm run dev
```

## Building for Production

```bash
npm run build
```

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