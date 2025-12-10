#!/bin/bash

# Seedream Bot Startup Script
# This script starts both the Telegram bot and admin panel

set -e

echo "════════════════════════════════════════════════════════"
echo "  Starting Seedream Bot Services"
echo "════════════════════════════════════════════════════════"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "   Please copy .env.example to .env and configure it"
    echo "   Command: cp .env.example .env"
    exit 1
fi

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "✓ Activating virtual environment..."
    source venv/bin/activate
else
    echo "ℹ️  No virtual environment found (venv/)"
    echo "   Continuing with system Python..."
fi

# Check if dependencies are installed
echo "✓ Checking dependencies..."
python -c "import aiogram" 2>/dev/null || {
    echo "❌ Error: Dependencies not installed!"
    echo "   Please run: pip install -r requirements.txt"
    exit 1
}

# Create data directory if it doesn't exist
mkdir -p data logs

# Check if admin user exists
echo "✓ Checking admin user..."
if [ ! -f "data/app.db" ]; then
    echo "⚠️  Database not found. You'll need to create an admin user."
    echo "   After the bot starts, run in another terminal:"
    echo "   python create_admin.py"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Starting Services..."
echo "════════════════════════════════════════════════════════"
echo ""

# Start bot in background
echo "🤖 Starting Telegram bot..."
python main.py &
BOT_PID=$!
echo "   ✓ Bot started (PID: $BOT_PID)"

# Wait a moment for bot to initialize
sleep 2

# Start admin panel in background
echo "🌐 Starting Admin Panel..."
python admin_panel.py &
ADMIN_PID=$!
echo "   ✓ Admin Panel started (PID: $ADMIN_PID)"

# Wait for admin panel to start
sleep 2

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✓ All Services Started Successfully!"
echo "════════════════════════════════════════════════════════"
echo ""
echo "📊 Services Status:"
echo "   • Telegram Bot:  Running (PID: $BOT_PID)"
echo "   • Admin Panel:   Running (PID: $ADMIN_PID)"
echo ""
echo "🔗 Access URLs:"
echo "   • Admin Panel:   http://localhost:8001/admin/login"
echo "   • Telegram Bot:  https://t.me/your_bot_username"
echo ""
echo "📝 Logs:"
echo "   • Bot logs:      tail -f logs/app.log"
echo "   • Admin logs:    In console where admin runs"
echo ""
echo "🛑 To stop services:"
echo "   kill $BOT_PID $ADMIN_PID"
echo ""
echo "   Or press Ctrl+C to stop this script and all services"
echo "════════════════════════════════════════════════════════"
echo ""

# Save PIDs to file for easy stopping
echo "$BOT_PID" > .bot.pid
echo "$ADMIN_PID" > .admin.pid

# Wait for processes (this keeps script running)
# Press Ctrl+C to stop
trap "echo ''; echo 'Stopping services...'; kill $BOT_PID $ADMIN_PID; rm -f .bot.pid .admin.pid; echo 'Services stopped.'; exit 0" INT TERM

wait
