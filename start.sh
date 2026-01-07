#!/bin/bash

echo "================================"
echo "🚀 Starting Mirai Dashboard"
echo "================================"

# Check Python version
echo "📍 Python version:"
python3 --version

# Start Python backend on port 8080 in background
echo ""
echo "🐍 Starting Python Reports API on port 8080..."
cd python_backend

# Test imports first
echo "🔍 Testing Python imports..."
if python3 -c "import simple_server" 2>&1; then
  echo "✅ Python imports successful"
else
  echo "❌ Python import test failed!"
  echo "Attempting to start anyway to see full error..."
fi

# Start Python server in background, output to both console and file
echo "🚀 Launching Python server..."
python3 simple_server.py > ../python.log 2>&1 &
PYTHON_PID=$!
cd ..

# Give Python time to start
echo "⏳ Waiting for Python to initialize..."
sleep 5

# Check if Python process is still running
if kill -0 $PYTHON_PID 2>/dev/null; then
  echo "✅ Python process is running (PID: $PYTHON_PID)"

  # Try to verify it's listening on port 8080
  echo "🔍 Checking if Python is listening on port 8080..."
  sleep 2
  if command -v nc >/dev/null 2>&1; then
    if nc -z localhost 8080 2>/dev/null; then
      echo "✅ Python backend is ready on port 8080"
    else
      echo "⚠️  Python process running but port 8080 not responding yet"
    fi
  fi
else
  echo "❌ Python process failed to start!"
  echo "📄 Python log output:"
  cat python.log 2>/dev/null || echo "(No log file found)"
  echo "⚠️  Continuing with Node.js only..."
fi

# Start Node.js backend on main port (foreground)
echo ""
echo "📦 Starting Node.js server..."
cd server
node index.js

# Cleanup: If Node.js exits, kill Python too
if kill -0 $PYTHON_PID 2>/dev/null; then
  echo "🛑 Stopping Python backend..."
  kill $PYTHON_PID 2>/dev/null
fi
