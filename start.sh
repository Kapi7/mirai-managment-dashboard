#!/bin/bash

echo "================================"
echo "🚀 Starting Mirai Dashboard"
echo "================================"
echo "📊 Reports will use external API: mirai-reports.onrender.com"
echo ""

# Start Node.js backend on main port
echo "📦 Starting Node.js server..."
cd server
node index.js
