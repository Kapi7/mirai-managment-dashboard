#!/bin/bash

# Start Python backend on port 8080 in background
echo "🐍 Starting Python Reports API on port 8080..."
cd python_backend
python3 server.py > ../python.log 2>&1 &
PYTHON_PID=$!
cd ..

# Wait for Python to start
sleep 3
echo "✅ Python API started (PID: $PYTHON_PID)"

# Start Node.js backend on main port (foreground)
echo "📦 Starting Node.js server..."
cd server
node index.js

# If Node.js exits, kill Python too
kill $PYTHON_PID 2>/dev/null
