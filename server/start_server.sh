#!/usr/bin/env bash

echo "🚀 Starting Laser Monitor Dashboard Server..."
echo "📁 Working directory: $(pwd)"
echo "🌐 Dashboard will be available at: http://localhost:5000"
echo ""

cd "$(dirname "$0")/.."
nix develop -c python server/app.py