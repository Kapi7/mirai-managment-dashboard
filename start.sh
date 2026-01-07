#!/bin/bash
set -e

echo "🚀 Starting Mirai Dashboard (Node.js only)"

# Just start Node.js - clean and simple
cd server
exec node index.js
