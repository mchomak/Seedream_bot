#!/bin/bash

# Seedream Bot Stop Script
# This script stops both the Telegram bot and admin panel

echo "════════════════════════════════════════════════════════"
echo "  Stopping Seedream Bot Services"
echo "════════════════════════════════════════════════════════"
echo ""

# Check if PID files exist
if [ -f .bot.pid ] && [ -f .admin.pid ]; then
    BOT_PID=$(cat .bot.pid)
    ADMIN_PID=$(cat .admin.pid)

    echo "🛑 Stopping Telegram bot (PID: $BOT_PID)..."
    kill $BOT_PID 2>/dev/null && echo "   ✓ Bot stopped" || echo "   ⚠️  Bot not running"

    echo "🛑 Stopping Admin Panel (PID: $ADMIN_PID)..."
    kill $ADMIN_PID 2>/dev/null && echo "   ✓ Admin Panel stopped" || echo "   ⚠️  Admin Panel not running"

    # Clean up PID files
    rm -f .bot.pid .admin.pid
else
    echo "⚠️  PID files not found. Searching for processes..."

    # Try to find and kill by process name
    BOT_PIDS=$(pgrep -f "python main.py")
    ADMIN_PIDS=$(pgrep -f "python admin_panel.py")

    if [ -n "$BOT_PIDS" ]; then
        echo "🛑 Stopping bot processes: $BOT_PIDS"
        kill $BOT_PIDS 2>/dev/null
        echo "   ✓ Bot stopped"
    else
        echo "   ℹ️  No bot process found"
    fi

    if [ -n "$ADMIN_PIDS" ]; then
        echo "🛑 Stopping admin panel processes: $ADMIN_PIDS"
        kill $ADMIN_PIDS 2>/dev/null
        echo "   ✓ Admin Panel stopped"
    else
        echo "   ℹ️  No admin panel process found"
    fi
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✓ Services Stopped"
echo "════════════════════════════════════════════════════════"
