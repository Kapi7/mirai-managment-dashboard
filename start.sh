#!/bin/bash
set -e

echo "🚀 Starting Mirai Dashboard with Python backend + Node.js frontend"

# Install Python dependencies
echo "📦 Installing Python dependencies..."
cd python_backend

# Use venv if it exists (local dev), otherwise install globally (Render)
if [ -d "venv" ]; then
  echo "Using existing virtualenv"
  source venv/bin/activate
else
  echo "Installing packages globally"
  python3 -m pip install -r requirements.txt --quiet || pip install -r requirements.txt --quiet
fi

# Start Python backend on port 8080 in background
echo "🐍 Starting Python reports backend on port 8080..."
uvicorn simple_server:app --host 0.0.0.0 --port 8080 &
PYTHON_PID=$!

# Give Python backend a moment to start
sleep 3

# Check if Python backend is running
if ! kill -0 $PYTHON_PID 2>/dev/null; then
  echo "❌ Python backend failed to start"
  exit 1
fi

echo "✅ Python backend running (PID: $PYTHON_PID)"

# Build frontend
echo "📦 Building frontend..."
cd ..
npm install --production=false --quiet
npm run build

# Start Node.js server on main port (10000 for Render, or PORT env var)
echo "🚀 Starting Node.js server on port ${PORT:-10000}..."
cd server
exec node index.js
