# Mirai Insights Dashboard - Development Guide

## Architecture

This is an integrated management dashboard with dual backend:

```
┌─────────────────────────────────────────────┐
│         React Frontend (Vite)               │
│  - Reports (Analytics)                      │
│  - Korealy Tracking                         │
│  - Settings                                 │
└─────────────────┬───────────────────────────┘
                  │
         ┌────────┴────────┐
         │                 │
    ┌────▼────┐      ┌────▼────┐
    │ Node.js │      │ Python  │
    │ Backend │      │ FastAPI │
    │ :3001   │      │ :8080   │
    └─────────┘      └─────────┘
         │                │
    ┌────▼────┐      ┌────▼────────────────┐
    │ Shopify │      │ Shopify + Google    │
    │ Gmail   │      │ Meta + PayPal       │
    └─────────┘      └─────────────────────┘
```

### Node.js Backend (port 3001)
- Korealy email processing
- Shopify order fulfillment
- Gmail OAuth integration

### Python Backend (port 8080)
- Business reports API
- Multi-source data aggregation
- Metrics calculation

## Running Locally

### Option 1: All-in-One Script
```bash
./start-all.sh
```

This starts both servers simultaneously.

### Option 2: Manual Start

**Terminal 1 - Node.js:**
```bash
node server/index.js
```

**Terminal 2 - Python:**
```bash
cd python_backend
python server.py
```

**Terminal 3 - Frontend (dev mode):**
```bash
npm run dev
```

## Environment Variables

### Root `.env` (Node.js)
```env
VITE_API_URL=http://localhost:3001
SHOPIFY_STORE=xxx.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxx
GMAIL_CLIENT_ID=xxx
GMAIL_CLIENT_SECRET=xxx
GMAIL_REFRESH_TOKEN=xxx
```

### `python_backend/.env` (Python)
```env
SHOPIFY_STORE=xxx.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxx
GOOGLE_ADS_CUSTOMER_ID=xxx
META_ACCESS_TOKEN=xxx
PAYPAL_CLIENT_ID=xxx
PAYPAL_CLIENT_SECRET=xxx
```

## Deployment Strategy

### Current Setup (Safe Migration)
- **mirai-reports.onrender.com** - Live system (automation, alerts)
- **mirai-insights.onrender.com** - This dashboard (reporting only)

The dashboard reads reports from the integrated Python backend, while all automated tasks (Telegram alerts, cron jobs) continue running on the separate live system.

### Future: Full Integration
Once tested and stable, all services can be consolidated into a single deployment.

## Adding New Features

1. **New Report/Chart**: Add to `src/pages/Reports.jsx`
2. **New Python API**: Add endpoint in `python_backend/server.py`
3. **New Management Tool**: Create new page in `src/pages/`
4. **New Backend Operation**: Add to `server/index.js`

## Testing

```bash
# Build production bundle
npm run build

# Test Python API
cd python_backend
python -m pytest  # (if tests exist)
```

## Production Build

```bash
npm run build
```

The build output includes:
- `dist/` - React frontend (served by Node.js)
- `python_backend/` - FastAPI server (runs separately)
