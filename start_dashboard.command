#!/bin/zsh
# Double-clickable macOS launcher for Sommelier Wine Cellar Agent
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "🍷 Starting Wine Cellar Dashboard..."
open "http://localhost:8002"
python3 "$DIR/cellar" serve --port 8002
