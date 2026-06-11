#!/bin/bash
set -e

echo "🎁 Telegram Gift Monitor — Setup"
echo "================================="

command -v python3 >/dev/null 2>&1 || { echo "❌ Python 3 is required."; exit 1; }
command -v pip3 >/dev/null 2>&1 || { echo "❌ pip3 is required."; exit 1; }

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED="3.10"
if [ "$(printf '%s\n' "$REQUIRED" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED" ]; then
    echo "❌ Python $REQUIRED+ required (found $PYTHON_VERSION)"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION"

echo ""
echo "📦 Installing dependencies..."
pip3 install -r requirements.txt --quiet

echo ""
echo "📁 Creating directories..."
mkdir -p data logs sessions

echo ""
if [ ! -f "settings.json" ]; then
    cp config/settings.example.json settings.json
    echo "✅ settings.json created from template"
    echo "   ⚠️  Edit settings.json with your credentials before running!"
else
    echo "✅ settings.json already exists"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit settings.json — add your Telegram API credentials"
echo "  2. Run: python main.py validate-config"
echo "  3. Run: python main.py start --monitor-only  (safe first run)"
echo "  4. Run: python main.py start --dry-run       (test buying logic)"
echo "  5. Run: python main.py start                 (full mode)"
echo ""
echo "Dashboard will be at: http://localhost:8080"
