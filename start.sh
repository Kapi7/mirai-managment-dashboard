#!/bin/bash
set -e

echo "🚀 Starting Mirai Dashboard services..."

# Start Python backend
echo "📊 Starting Python backend on port 8080..."
cd python_backend
python3 server.py &
PYTHON_PID=$!
echo "Python backend PID: $PYTHON_PID"

# Wait for Python backend to be ready
echo "⏳ Waiting for Python backend to be ready..."
sleep 5

# Check if Python backend is running
if ! curl -s http://localhost:8080/health > /dev/null; then
    echo "❌ Python backend failed to start"
    kill $PYTHON_PID 2>/dev/null || true
    exit 1
fi
echo "✅ Python backend is ready"

# Start Node.js server
echo "📱 Starting Node.js server..."
cd ..
exec node server/index.js
