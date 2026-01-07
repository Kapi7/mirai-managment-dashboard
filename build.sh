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
pip install -r requirements.txt
cd ..

echo "✅ Build complete!"
