# Seedream Bot - Complete Launch Guide

## Quick Start (Development)

### Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- PostgreSQL or SQLite (SQLite works for development)

---

## Step-by-Step Setup

### 1. Install Dependencies

```bash
# Install all required packages
pip install aiogram sqlalchemy asyncpg aiosqlite redis loguru yookassa fastapi uvicorn passlib[bcrypt] python-multipart jinja2
```

Or if you have a requirements.txt:
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example file:
```bash
cp .env.example .env
```

Edit `.env` file with your settings:

```env
# App Configuration
APP_NAME=seedream_bot
APP_ENV=dev
DEBUG=true
LOG_LEVEL=INFO

# Telegram Bot
TELEGRAM_BOT_TOKEN=123456789:YOUR_ACTUAL_BOT_TOKEN_FROM_BOTFATHER
TELEGRAM_ALERTS_CHAT_ID=123456789

# Database (SQLite for development)
DATABASE_URL=sqlite+aiosqlite:///./data/app.db

# Redis (optional for development)
REDIS_URL=redis://localhost:6379/0

# YooKassa Payment (optional, can configure later)
YOOKASSA_SHOP_ID=your_shop_id
YOOKASSA_SECRET_KEY=live_your_secret_key
YOOKASSA_RETURN_URL=https://t.me/your_bot_username

# Admin Panel
ADMIN_SECRET_KEY=generated_secret_key_at_least_32_characters
ADMIN_PORT=8001

# Seedream API
SEEDREAM_API=your_seedream_api_key
```

**Important settings to configure:**

1. **TELEGRAM_BOT_TOKEN**: Get from [@BotFather](https://t.me/BotFather)
   - Send `/newbot` to BotFather
   - Follow instructions
   - Copy the token

2. **ADMIN_SECRET_KEY**: Generate a secure key
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. **SEEDREAM_API**: Your Seedream API key

### 3. Create Database Directory (SQLite only)

```bash
mkdir -p data
```

The database will be created automatically on first run.

### 4. Create Admin User

```bash
python create_admin.py
```

Example interaction:
```
==================================================
Create Admin User for Seedream Admin Panel
==================================================

Enter admin username: admin
Enter admin email (optional, press Enter to skip): admin@example.com
Enter admin password: ********
Confirm password: ********

==================================================
✓ Admin user created successfully!
==================================================
Username: admin
Email: admin@example.com
Superuser: Yes

You can now login to the admin panel at:
http://localhost:8001/admin/login
==================================================
```

---

## Launch Options

### Option 1: Run Separately (Recommended for Development)

#### Terminal 1: Start the Bot

```bash
python main.py
```

Expected output:
```
2025-12-10 15:30:00 | INFO | Starting bot…
2025-12-10 15:30:01 | INFO | Bot started successfully
```

#### Terminal 2: Start the Admin Panel

```bash
python admin_panel.py
```

Expected output:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8001
```

Now access:
- **Bot**: Telegram at `t.me/your_bot_username`
- **Admin Panel**: Browser at `http://localhost:8001/admin/login`

---

### Option 2: Run with Process Manager (Recommended for Production)

Create a startup script `start_all.sh`:

```bash
#!/bin/bash

# Start all services

echo "Starting Seedream Bot services..."

# Start bot in background
python main.py &
BOT_PID=$!
echo "Bot started with PID: $BOT_PID"

# Start admin panel in background
python admin_panel.py &
ADMIN_PID=$!
echo "Admin panel started with PID: $ADMIN_PID"

echo ""
echo "Services started successfully!"
echo "Bot PID: $BOT_PID"
echo "Admin Panel PID: $ADMIN_PID"
echo "Admin Panel URL: http://localhost:8001/admin/login"
echo ""
echo "To stop services:"
echo "kill $BOT_PID $ADMIN_PID"
```

Make it executable and run:
```bash
chmod +x start_all.sh
./start_all.sh
```

To stop:
```bash
# Find PIDs
ps aux | grep python

# Kill processes
kill <BOT_PID> <ADMIN_PID>
```

---

### Option 3: Using systemd (Production on Linux)

Create bot service file: `/etc/systemd/system/seedream-bot.service`

```ini
[Unit]
Description=Seedream Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Seedream_bot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Create admin panel service: `/etc/systemd/system/seedream-admin.service`

```ini
[Unit]
Description=Seedream Admin Panel
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Seedream_bot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python admin_panel.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start services:
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable seedream-bot
sudo systemctl enable seedream-admin

# Start services
sudo systemctl start seedream-bot
sudo systemctl start seedream-admin

# Check status
sudo systemctl status seedream-bot
sudo systemctl status seedream-admin

# View logs
sudo journalctl -u seedream-bot -f
sudo journalctl -u seedream-admin -f
```

Manage services:
```bash
# Stop services
sudo systemctl stop seedream-bot
sudo systemctl stop seedream-admin

# Restart services
sudo systemctl restart seedream-bot
sudo systemctl restart seedream-admin

# Disable auto-start
sudo systemctl disable seedream-bot
sudo systemctl disable seedream-admin
```

---

### Option 4: Using Docker (Advanced)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  bot:
    build: .
    command: python main.py
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    env_file:
      - .env
    restart: unless-stopped
    depends_on:
      - redis

  admin:
    build: .
    command: python admin_panel.py
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    env_file:
      - .env
    ports:
      - "8001:8001"
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

Run with Docker:
```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f bot
docker-compose logs -f admin

# Stop
docker-compose down

# Restart
docker-compose restart
```

---

## Verify Installation

### 1. Check Bot is Running

Send `/start` to your bot on Telegram. You should receive a welcome message.

### 2. Check Admin Panel

1. Open browser to `http://localhost:8001/admin/login`
2. Login with your admin credentials
3. You should see the dashboard

### 3. Check Logs

Bot logs are in:
- Console output
- `logs/` directory (if configured)

Admin panel logs are in console output.

---

## Common Issues & Solutions

### Issue: "ModuleNotFoundError"

**Solution:** Install missing dependencies
```bash
pip install <missing_module>
```

### Issue: "Database locked" (SQLite)

**Solution:** Only one process can write to SQLite at a time
- Use PostgreSQL for production
- Or ensure only one bot instance is running

### Issue: "Port 8001 already in use"

**Solution:**
```bash
# Find process using port
lsof -ti:8001

# Kill it
kill $(lsof -ti:8001)

# Or use different port
ADMIN_PORT=8002 python admin_panel.py
```

### Issue: "Invalid bot token"

**Solution:**
- Check TELEGRAM_BOT_TOKEN in .env
- Get new token from @BotFather
- Make sure no extra spaces

### Issue: Admin panel shows "Cannot connect to database"

**Solution:**
- Check DATABASE_URL in .env
- Ensure database file exists (for SQLite)
- Check database permissions

---

## Production Deployment

### 1. Use PostgreSQL

Update `.env`:
```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/seedream
```

### 2. Setup Reverse Proxy (nginx)

`/etc/nginx/sites-available/seedream-admin`:

```nginx
server {
    listen 80;
    server_name admin.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and get SSL:
```bash
sudo ln -s /etc/nginx/sites-available/seedream-admin /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d admin.yourdomain.com
```

### 3. Security Checklist

- ✅ Use strong admin passwords (12+ characters)
- ✅ Enable HTTPS for admin panel
- ✅ Use PostgreSQL instead of SQLite
- ✅ Set DEBUG=false in production
- ✅ Restrict admin panel access by IP (firewall)
- ✅ Regular backups of database
- ✅ Keep dependencies updated
- ✅ Monitor logs regularly

---

## Monitoring

### Check if services are running:

```bash
# Check bot process
ps aux | grep "python main.py"

# Check admin panel process
ps aux | grep "python admin_panel.py"

# Check ports
netstat -tulpn | grep :8001
```

### View logs:

```bash
# Real-time bot logs
tail -f logs/app.log

# Real-time admin logs
# (shown in console where admin_panel.py is running)
```

---

## Backup & Restore

### Backup Database (SQLite):

```bash
# Create backup
cp data/app.db data/app.db.backup-$(date +%Y%m%d)

# Restore backup
cp data/app.db.backup-20251210 data/app.db
```

### Backup Database (PostgreSQL):

```bash
# Create backup
pg_dump -U user seedream > backup-$(date +%Y%m%d).sql

# Restore backup
psql -U user seedream < backup-20251210.sql
```

---

## Quick Reference Commands

```bash
# Development
python main.py                    # Start bot
python admin_panel.py            # Start admin panel
python create_admin.py           # Create admin user

# Production (systemd)
sudo systemctl start seedream-bot     # Start bot
sudo systemctl start seedream-admin   # Start admin panel
sudo systemctl status seedream-bot    # Check bot status
sudo systemctl stop seedream-bot      # Stop bot
sudo journalctl -u seedream-bot -f    # View bot logs

# Docker
docker-compose up -d             # Start all services
docker-compose logs -f           # View all logs
docker-compose restart           # Restart services
docker-compose down              # Stop all services
```

---

## Support

If you encounter issues:
1. Check logs for error messages
2. Verify .env configuration
3. Ensure all dependencies are installed
4. Check database connectivity
5. Review this guide for common issues

---

## Next Steps

1. ✅ Launch the bot
2. ✅ Launch the admin panel
3. ✅ Test basic functionality
4. 🔄 Configure YooKassa payments (if needed)
5. 🔄 Set up monitoring
6. 🔄 Configure backups
7. 🔄 Deploy to production server

Enjoy your Seedream bot! 🤖✨
