#!/bin/bash
set -e

echo "🚀 Starting Mirai Dashboard services..."

# Copy secret files if they exist (Render Secret Files feature)
if [ -f /etc/secrets/google-ads.yaml ]; then
    echo "📄 Copying google-ads.yaml from Render secrets..."
    cp /etc/secrets/google-ads.yaml python_backend/google-ads.yaml
fi

# Start Python backend
echo "📊 Starting Python backend on port 8080..."
cd python_backend

# Ensure all required packages are installed
pip install --quiet sqlalchemy[asyncio] asyncpg psycopg2-binary PyJWT httpx 2>/dev/null || true

uvicorn server:app --host 127.0.0.1 --port 8080 2>&1 | sed 's/^/[PYTHON] /' &
PYTHON_PID=$!
echo "Python backend PID: $PYTHON_PID"

# Wait for Python backend with retry logic
echo "⏳ Waiting for Python backend to be ready..."
MAX_RETRIES=10
RETRY_COUNT=0
RETRY_DELAY=2

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "✅ Python backend is ready (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"
        break
    fi

    # Check if process is still running
    if ! kill -0 $PYTHON_PID 2>/dev/null; then
        echo "❌ Python backend process died during startup"
        exit 1
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        echo "⏳ Python backend not ready yet, retrying in ${RETRY_DELAY}s... (attempt $RETRY_COUNT/$MAX_RETRIES)"
        sleep $RETRY_DELAY
    else
        echo "❌ Python backend failed to start after $MAX_RETRIES attempts"
        kill $PYTHON_PID 2>/dev/null || true
        exit 1
    fi
done

# Start Node.js server
echo "📱 Starting Node.js server..."
cd ..
exec node server/index.js
