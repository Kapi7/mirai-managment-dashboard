#!/bin/bash

# Start both Node.js and Python servers

echo "🚀 Starting Mirai Insights Dashboard..."

# Start Python FastAPI server on port 8080
echo "📊 Starting Python Reports API on port 8080..."
cd python_backend && python3 server.py &
PYTHON_PID=$!

# Wait a moment for Python server to start
sleep 2

# Start Node.js server on port 3001
echo "📦 Starting Node.js server on port 3001..."
cd .. && node server/index.js &
NODE_PID=$!

echo ""
echo "✅ Both servers started!"
echo "   - Node.js (Korealy): http://localhost:3001"
echo "   - Python (Reports): http://localhost:8080"
echo ""
echo "Press Ctrl+C to stop all servers"

# Wait for both processes
wait $PYTHON_PID $NODE_PID
