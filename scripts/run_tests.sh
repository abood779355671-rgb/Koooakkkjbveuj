#!/bin/bash
set -e
cd "$(dirname "$0")/.."
echo "🧪 Running tests..."
pip install pytest pytest-asyncio --quiet
python -m pytest tests/ -v --tb=short
