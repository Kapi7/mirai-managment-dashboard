#!/bin/bash

# Start script for Render deployment with both Node.js and Python

echo "🚀 Starting Mirai Dashboard with dual backend..."

# Start Python FastAPI server on port 8080 in background
echo "📊 Starting Python Reports API..."
cd python_backend
python3 server.py > ../python.log 2>&1 &
PYTHON_PID=$!
cd ..

# Give Python a moment to start
sleep 3

# Start Node.js server on Render's PORT (foreground)
echo "📦 Starting Node.js server..."
node server/index.js

# If Node.js exits, kill Python too
kill $PYTHON_PID 2>/dev/null
