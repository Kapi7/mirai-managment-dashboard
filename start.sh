#!/bin/bash

# Start Python backend on port 8080 in background
echo "🐍 Starting Python Reports API on port 8080..."
cd python_backend

# Test if Python can start (will show errors immediately if it fails)
python3 -c "import server" 2>&1 | head -20

# Now start Python in background, but still log errors
python3 server.py 2>&1 | tee ../python.log &
PYTHON_PID=$!
cd ..

# Wait for Python to start
sleep 5
echo "✅ Python API started (PID: $PYTHON_PID)"

# Check if Python process is actually running
if ps -p $PYTHON_PID > /dev/null 2>&1; then
  echo "✅ Python process is running"
else
  echo "❌ Python process failed to start - check logs above"
  cat python.log 2>/dev/null || echo "No python.log found"
fi

# Start Node.js backend on main port (foreground)
echo "📦 Starting Node.js server..."
cd server
node index.js

# If Node.js exits, kill Python too
kill $PYTHON_PID 2>/dev/null
