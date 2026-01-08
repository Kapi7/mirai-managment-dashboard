# Mirai Dashboard Architecture

## 🏗️ Deployment Architecture

### Single Container Setup (Render)

```
Internet Request
    ↓
Render Load Balancer (https://your-app.onrender.com)
    ↓
    ┌─────────────────────────────────────────────┐
    │  Your Container (Single Machine)            │
    │                                              │
    │  ┌──────────────────────────────────────┐  │
    │  │ Node.js Express Server                │  │
    │  │ Port: 10000 (PUBLIC)                  │  │
    │  │                                        │  │
    │  │ - Serves static React frontend       │  │
    │  │ - Proxies API requests to Python     │  │
    │  │ - Handles Gmail/Shopify OAuth        │  │
    │  └──────────────────────────────────────┘  │
    │             ↓ localhost:8080                │
    │  ┌──────────────────────────────────────┐  │
    │  │ Python FastAPI Backend                │  │
    │  │ Port: 8080 (INTERNAL ONLY)            │  │
    │  │                                        │  │
    │  │ - Reports generation                  │  │
    │  │ - Pricing logic                       │  │
    │  │ - Shopify/Meta/Google integrations   │  │
    │  └──────────────────────────────────────┘  │
    └─────────────────────────────────────────────┘
```

## 🔐 Why Localhost is Correct

### 1. Same Container
Both processes run in the SAME container/VM, so they share the same network stack. `localhost:8080` means "connect to port 8080 on THIS machine."

### 2. Security Benefits
- Python backend (port 8080) is NOT exposed to the internet
- Only Node.js server (port 10000) accepts public traffic
- Python backend can only be accessed by Node.js on the same machine
- No external attacks can directly reach Python backend

### 3. Performance
- Localhost connections are ultra-fast (no network overhead)
- No latency from external network calls
- Reduced bandwidth usage

## 🛡️ Error Handling

### Startup Failures

**Problem**: Python backend fails to start

**Detection**: 
- `start.sh` runs health checks with 10 retries (20 seconds total)
- If health check fails, deployment exits with error code 1
- Render shows deployment as failed

**Solution**:
- Check Render logs for Python errors
- Verify all environment variables are set
- Ensure `requirements.txt` dependencies install correctly

### Runtime Failures

**Problem**: Python backend crashes after successful startup

**Detection**:
- Node.js proxy catches connection errors (`ECONNREFUSED`)
- Returns HTTP 503 with user-friendly error message

**Response**:
```json
{
  "error": "Python backend unavailable. Please try again in a moment.",
  "details": "The pricing service is temporarily unavailable."
}
```

**Recovery**:
- Render automatically restarts the container if the main process dies
- New container starts both services fresh

### Timeout Handling

**Problem**: Python backend responds slowly (>30 seconds)

**Detection**:
- Node.js proxy has 30-second timeout on all requests
- Returns HTTP 504 Gateway Timeout

**Response**:
```json
{
  "error": "Request timeout",
  "details": "The pricing service took too long to respond."
}
```

## 📊 Request Flow Examples

### Successful Request
```
1. User clicks "Execute Price Update"
2. Frontend → POST https://your-app.onrender.com/reports-api/pricing/execute-updates
3. Node.js → POST http://localhost:8080/pricing/execute-updates
4. Python processes request
5. Python → Returns JSON response
6. Node.js → Returns JSON to frontend
7. Frontend updates UI
```

### Failed Request (Python Down)
```
1. User clicks "Execute Price Update"
2. Frontend → POST https://your-app.onrender.com/reports-api/pricing/execute-updates
3. Node.js → Attempts POST http://localhost:8080/pricing/execute-updates
4. Connection refused (ECONNREFUSED)
5. Node.js → Returns 503 error
6. Frontend shows "Service temporarily unavailable"
```

## 🔧 Environment Variables

### Required in Render Dashboard

```bash
# Backend URL (DO NOT CHANGE - must be localhost for same-container setup)
PYTHON_BACKEND_URL=http://localhost:8080

# Shopify
SHOPIFY_STORE=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxx

# PayPal
PAYPAL_CLIENT_ID=xxx
PAYPAL_CLIENT_SECRET=xxx

# Google Ads
GOOGLE_ADS_CUSTOMER_ID=xxx
GOOGLE_ADS_CONFIG=google-ads.yaml

# Meta
META_ACCESS_TOKEN=xxx
META_AD_ACCOUNT_ID=act_xxx

# (Add all other env vars from python_backend/.env)
```

## 🚀 Deployment Process

### 1. Build Phase
```bash
npm install          # Install Node.js dependencies
npm run build        # Build React frontend
cd python_backend && pip install -r requirements.txt
```

### 2. Startup Phase
```bash
bash start.sh
  ├── Start Python FastAPI (port 8080, background)
  ├── Wait & health check (10 retries, 2s delay)
  └── Start Node.js Express (port 10000, foreground)
```

### 3. Health Checks
- Python: `GET http://localhost:8080/health` → `{"status":"ok"}`
- Node.js: `GET http://localhost:10000/health` → `{"status":"ok"}`

## 🔄 Alternative Architecture (Not Used)

### Two Separate Services (More Complex)

```
Service 1: Python Backend (separate instance)
  → Has own public URL: https://python-backend.onrender.com
  
Service 2: Node.js Frontend (separate instance)  
  → Connects via: PYTHON_BACKEND_URL=https://python-backend.onrender.com
```

**Why we don't use this:**
- More expensive (2 instances instead of 1)
- Higher latency (network calls between services)
- More complex configuration
- Exposes Python backend to internet (security concern)
- Requires managing 2 separate deployments

## 📝 Troubleshooting

### "Cannot POST /reports-api/pricing/execute-updates"
**Cause**: Old code deployed (before POST route handler added)  
**Fix**: Ensure latest commit is deployed on Render

### "Python backend error: 404"
**Cause**: Python backend missing endpoint implementation  
**Fix**: Check `python_backend/server.py` has the endpoint

### "Python backend unavailable"
**Cause**: Python backend crashed or failed to start  
**Fix**: Check Render logs for Python errors, verify env vars

### Slow Requests
**Cause**: Python backend doing heavy processing  
**Fix**: Optimize Python code, consider caching, or increase timeout
