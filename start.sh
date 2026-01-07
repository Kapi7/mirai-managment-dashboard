#!/bin/bash

echo "================================"
echo "🚀 Starting Mirai Dashboard"
echo "================================"

# Force kill anything on ports 8080 and 10000
echo "🧹 Cleaning up ports..."
fuser -k 8080/tcp 2>/dev/null || true
fuser -k 10000/tcp 2>/dev/null || true
sleep 2

# Start Python backend on port 8080
echo "🐍 Starting Python Reports API on port 8080..."
cd python_backend
python3 simple_server.py > ../python.log 2>&1 &
PYTHON_PID=$!
cd ..

# Wait for Python to start
sleep 3
echo "✅ Python backend started (PID: $PYTHON_PID)"

# Start Node.js backend on main port
echo "📦 Starting Node.js server..."
cd server
node index.js

# Cleanup on exit
kill $PYTHON_PID 2>/dev/null || true
