#!/bin/bash
# ==============================================================================
# NewsAI Telegram Bot - Automated Ubuntu Server Setup Script
# ==============================================================================

set -e

echo "=========================================="
echo "🚀 Setting up NewsAI Bot on Ubuntu Server"
echo "=========================================="

# 1. Update system packages
echo "📦 Updating apt packages..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git curl

# 2. Create virtual environment
echo "🐍 Creating Python virtual environment (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Created venv directory."
else
    echo "ℹ️ venv already exists."
fi

# 3. Upgrade pip and install requirements
echo "📥 Installing Python dependencies into venv..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️ .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "👉 Please edit .env with: nano .env"
fi

echo "=========================================="
echo "✅ Setup Completed Successfully!"
echo "=========================================="
echo ""
echo "To run diagnostics:"
echo "  ./venv/bin/python test_news.py"
echo ""
echo "To test run the bot:"
echo "  ./venv/bin/python bot.py"
echo ""
echo "To setup systemd 24/7 background service:"
echo "  sudo cp newsai.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable newsai"
echo "  sudo systemctl start newsai"
echo "  sudo systemctl status newsai"

