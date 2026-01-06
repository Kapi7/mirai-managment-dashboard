#!/bin/bash
set -e

echo "📦 Installing frontend dependencies..."
npm install

echo "🏗️  Building frontend..."
npm run build

echo "📦 Installing backend dependencies..."
cd server
npm install

echo "✅ Build complete!"
