# Python Reports Backend

This folder contains the Python FastAPI server for business reports and analytics.

## What It Does

- Fetches live data from Shopify, Google Ads, Meta Ads, and PayPal
- Calculates operational metrics (COGS, shipping, profit, margins)
- Provides REST API endpoints for the dashboard

## API Endpoints

- `POST /daily-report` - Get KPIs for a date range
- `POST /ad-spend` - Get ad spend data
- `GET /health` - Health check

## Running Locally

1. **Install Python dependencies:**
   ```bash
   cd python_backend
   pip install -r requirements.txt
   ```

2. **Set up .env file** with credentials:
   - Shopify API keys
   - Google Ads credentials
   - Meta/Facebook credentials
   - PayPal API keys

3. **Run the server:**
   ```bash
   python server.py
   ```

   The server will start on http://localhost:8080

## Integration with Dashboard

The React dashboard (`src/pages/Reports.jsx`) connects to this API to display:
- Daily orders, revenue, profit
- Ad spend and ROI
- Operational metrics
- Margin analysis

## Note

This is a **read-only reporting API**. It does NOT handle:
- Order alerts (still on mirai-reports.onrender.com)
- Telegram notifications
- Automated cron jobs

Those automation tasks remain on the separate live system to avoid disruption.
