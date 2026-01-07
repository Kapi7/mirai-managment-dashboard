#!/bin/bash
set -e

echo "📦 Installing frontend dependencies..."
npm install

echo "🏗️  Building frontend..."
npm run build

echo "📦 Installing backend dependencies..."
cd server
npm install
cd ..

echo "🐍 Installing Python dependencies..."
cd python_backend
# Use minimal requirements for dashboard (no Telegram, no gspread, etc.)
pip3 install -r requirements_minimal.txt
cd ..

echo "✅ Build complete!"
