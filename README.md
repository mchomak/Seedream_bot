# Seedream Bot - AI Virtual Try-On Telegram Bot

 

<div align="center">

 

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)

![Aiogram](https://img.shields.io/badge/aiogram-3.x-blue.svg)

![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)

![License](https://img.shields.io/badge/license-MIT-green.svg)

 

**Powerful Telegram bot for AI-powered virtual try-on with comprehensive admin panel**

 

[Features](#features) • [Installation](#installation) • [Configuration](#configuration) • [Usage](#usage) • [Admin Panel](#admin-panel) • [Documentation](#documentation)

 

</div>

 

---

 

## 📋 Table of Contents

 

- [About](#about)

- [Features](#features)

- [Tech Stack](#tech-stack)

- [Prerequisites](#prerequisites)

- [Installation](#installation)

- [Configuration](#configuration)

- [Database Setup](#database-setup)

- [Launching the Bot](#launching-the-bot)

- [Launching the Admin Panel](#launching-the-admin-panel)

- [Admin Panel Features](#admin-panel-features)

- [Project Structure](#project-structure)

- [API Documentation](#api-documentation)

- [Deployment](#deployment)

- [Troubleshooting](#troubleshooting)

- [Contributing](#contributing)

- [License](#license)

 

---

 

## 🎯 About

 

Seedream Bot is a feature-rich Telegram bot that provides AI-powered virtual try-on services using the Seedream 4.0 neural network. Users can upload photos of clothing items and generate realistic images of models wearing those items with customizable parameters like background, pose, angle, and style.

 

The project includes:

- **Telegram Bot** - User-facing interface for image generation

- **Web Admin Panel** - Comprehensive management dashboard

- **Payment Integration** - Telegram Stars & YooKassa support

- **Analytics Dashboard** - Real-time metrics and reporting

 

---

 

## ✨ Features

 

### Bot Features

 

- 🎨 **AI Image Generation** - Generate realistic model photos from clothing items

- 📸 **Multi-Photo Upload** - Process multiple items at once

- 🎭 **Customization Options**:

  - Background selection (white, interior, street, studio)

  - Model parameters (gender, age, hair color)

  - Photo style and aspect ratio

  - Pose and angle adjustments

- 🔄 **Interactive Review System** - Approve, reject, or regenerate images

- 📐 **Angles & Poses Stage** - Create product profiles with multiple views

- 💳 **Dual Payment System**:

  - Telegram Stars (native payment)

  - YooKassa (bank cards, Russian market)

- 👤 **User Account System**:

  - Balance management

  - Transaction history

  - Generation archive (30 days)

  - Download functionality

- 🌍 **Multi-language** - Russian and English support

- 📱 **Persistent Keyboard** - Quick access to key features

 

### Admin Panel Features

 

- 🔐 **Secure Authentication** - Bcrypt password hashing, session management

- 📊 **Analytics Dashboard**:

  - Total users, active users (30 days)

  - Revenue metrics, average check

  - Generation statistics and success rates

- 👥 **User Management**:

  - Search by Telegram ID or username

  - View detailed user profiles

  - Manual balance adjustment with audit trail

  - Transaction and generation history

- 💰 **Financial Management**:

  - Transaction list with advanced filters

  - Payment tracking (Stars, YooKassa)

  - Export to CSV

- 📈 **Analytics & Reporting**:

  - Key performance indicators (KPIs)

  - User activity metrics

  - Revenue analytics

- 📥 **Data Export** - CSV export for users and transactions

- 📝 **Audit Logging** - Complete trail of all admin actions

- 🎨 **Modern UI** - Bootstrap 5, responsive design

 

---

 

## 🛠 Tech Stack

 

### Backend

- **Python 3.10+** - Core language

- **aiogram 3.x** - Telegram Bot framework

- **FastAPI** - Web admin panel

- **SQLAlchemy 2.0** - Database ORM

- **PostgreSQL / SQLite** - Database

 

### Frontend (Admin Panel)

- **Bootstrap 5** - UI framework

- **Font Awesome** - Icons

- **Jinja2** - Template engine

- **Chart.js** - Analytics charts (ready for integration)

 

### Additional Services

- **Redis** - FSM storage (optional)

- **YooKassa SDK** - Payment processing

- **Seedream API** - AI image generation

- **bcrypt** - Password hashing

 

---

 

## 📦 Prerequisites

 

Before installing, ensure you have:

 

- **Python 3.10 or higher**

- **pip** (Python package manager)

- **PostgreSQL** (recommended for production) or **SQLite** (for development)

- **Redis** (optional, for FSM storage)

- **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))

- **Seedream API Key**

 

---

 

## 🚀 Installation

 

### Step 1: Clone the Repository

 

```bash

git clone https://github.com/yourusername/seedream_bot.git

cd seedream_bot

```

 

### Step 2: Create Virtual Environment

 

**Linux/macOS:**

```bash

python3 -m venv venv

source venv/bin/activate

```

 

**Windows:**

```bash

python -m venv venv

venv\Scripts\activate

```

 

### Step 3: Install Dependencies

 

```bash

pip install -r requirements.txt

```

 

**Dependencies include:**

- `aiogram>=3.0.0` - Telegram bot framework

- `sqlalchemy>=2.0.0` - Database ORM

- `fastapi>=0.104.0` - Admin panel

- `uvicorn>=0.24.0` - ASGI server

- `yookassa>=3.0.0` - Payment processing

- `bcrypt>=4.0.0` - Password hashing

- And more...

 

---

 

## ⚙️ Configuration

 

### Step 1: Copy Environment Template

 

```bash

cp .env.example .env

```

 

### Step 2: Edit `.env` File

 

Open `.env` in your text editor and configure:

 

```env

# Application Settings

APP_NAME=seedream_bot

APP_ENV=dev

DEBUG=true

LOG_LEVEL=INFO

 

# Telegram Bot Configuration

TELEGRAM_BOT_TOKEN=123456789:YOUR_BOT_TOKEN_FROM_BOTFATHER

TELEGRAM_ALERTS_CHAT_ID=your_telegram_user_id

 

# Database Configuration

# For development (SQLite):

DATABASE_URL=sqlite+aiosqlite:///./data/app.db

 

# For production (PostgreSQL):

# DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/seedream

 

# Redis (optional, for FSM storage)

REDIS_URL=redis://localhost:6379/0

 

# Seedream API

SEEDREAM_API=your_seedream_api_key_here

 

# YooKassa Payment (optional, configure when needed)

YOOKASSA_SHOP_ID=your_shop_id

YOOKASSA_SECRET_KEY=live_your_secret_key

YOOKASSA_RETURN_URL=https://t.me/your_bot_username

 

# Admin Panel Configuration

ADMIN_SECRET_KEY=your_generated_secret_key_here

ADMIN_PORT=8001

```

 

### Step 3: Generate Admin Secret Key

 

```bash

python -c "import secrets; print(secrets.token_urlsafe(32))"

```

 

Copy the output and paste it as `ADMIN_SECRET_KEY` in your `.env` file.

 

### Step 4: Get Telegram Bot Token

 

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)

2. Send `/newbot` command

3. Follow the instructions to create your bot

4. Copy the token and paste it as `TELEGRAM_BOT_TOKEN` in `.env`

 

---

 

## 💾 Database Setup

 

### Option 1: SQLite (Development)

 

SQLite requires no additional setup. The database file will be created automatically.

 

```bash

# Create data directory

mkdir -p data

 

# Database will be created automatically on first run

```

 

### Option 2: PostgreSQL (Production)

 

#### Install PostgreSQL

 

**Ubuntu/Debian:**

```bash

sudo apt update

sudo apt install postgresql postgresql-contrib

```

 

**macOS (Homebrew):**

```bash

brew install postgresql

brew services start postgresql

```

 

**Windows:**

Download from [postgresql.org](https://www.postgresql.org/download/windows/)

 

#### Create Database

 

```bash

# Connect to PostgreSQL

sudo -u postgres psql

 

# Create database and user

CREATE DATABASE seedream;

CREATE USER seedream_user WITH PASSWORD 'your_password';

GRANT ALL PRIVILEGES ON DATABASE seedream TO seedream_user;

\q

```

 

#### Update `.env`

 

```env

DATABASE_URL=postgresql+asyncpg://seedream_user:your_password@localhost:5432/seedream

```

 

### Database Migrations

 

The database tables will be created automatically when you first run the bot or admin panel. No manual migration needed!

 

---

 

## 🤖 Launching the Bot

 

### Option 1: Quick Start (Automated)

 

**Linux/macOS:**

```bash

./start.sh

```

 

**Windows:**

Create `start.bat`:

```batch

@echo off

start "Seedream Bot" python main.py

start "Seedream Admin" python admin_panel.py

echo Services started!

pause

```

 

Then double-click `start.bat`

 

### Option 2: Manual Start

 

**Terminal 1 - Start the Bot:**

```bash

python main.py

```

 

**Expected output:**

```

2025-12-10 15:30:00 | INFO | Starting bot…

2025-12-10 15:30:01 | INFO | Bot started successfully

```

 

**Terminal 2 - Start the Admin Panel:**

```bash

python admin_panel.py

```

 

**Expected output:**

```

INFO:     Started server process [12345]

INFO:     Waiting for application startup.

INFO:     Application startup complete.

INFO:     Uvicorn running on http://0.0.0.0:8001

```

 

### Verify Bot is Running

 

1. Open Telegram

2. Search for your bot by username

3. Send `/start` command

4. You should receive a welcome message

 

---

 

## 🌐 Launching the Admin Panel

 

### Step 1: Create Admin User

 

Before accessing the admin panel, create an admin account:

 

```bash

python create_admin.py

```

 

**Follow the prompts:**

```

Enter admin username: admin

Enter admin email (optional): admin@example.com

Enter admin password: ********

Confirm password: ********

 

✓ Admin user created successfully!

```

 

### Step 2: Start Admin Panel

 

```bash

python admin_panel.py

```

 

### Step 3: Access Admin Panel

 

Open your browser and navigate to:

```

http://localhost:8001/admin/login

```

 

Login with your admin credentials.

 

### Admin Panel URLs

 

- **Login**: `http://localhost:8001/admin/login`

- **Dashboard**: `http://localhost:8001/admin/`

- **Users**: `http://localhost:8001/admin/users`

- **Transactions**: `http://localhost:8001/admin/transactions`

- **Logs**: `http://localhost:8001/admin/logs`

 

---

 

## 👨‍💼 Admin Panel Features

 

### Dashboard

- Total users count

- Active users (30 days)

- Total revenue and average check

- Generation statistics

- Recent transactions

- Recent user registrations

 

### User Management

- **Search** - Find users by Telegram ID or username

- **View Profiles** - Complete user information

- **Balance Adjustment** - Add/deduct credits manually

- **History** - View transactions and generations

- **Export** - Download user data as CSV

 

### Financial Management

- **Transaction List** - All payments with filters

- **Filter by User** - See specific user's payments

- **Filter by Status** - succeeded, pending, failed, canceled

- **Export** - Download transaction data as CSV

 

### Admin Logs

- Complete audit trail

- Action logging with details

- IP address tracking

- JSON data view

 

### Data Export

- Users export (CSV)

- Transactions export (CSV)

- Ready for Excel/Google Sheets

 

---

 

## 📁 Project Structure

 

```

Seedream_bot/

├── main.py                     # Bot entry point

├── admin_panel.py              # Admin panel application

├── create_admin.py             # Admin user creation utility

├── start.sh / stop.sh          # Service management scripts

├── requirements.txt            # Python dependencies

├── .env.example                # Environment template

├── README.md                   # This file

│

├── admin/                      # Admin panel files

│   ├── templates/              # HTML templates

│   │   ├── base.html           # Base layout

│   │   ├── login.html          # Login page

│   │   ├── dashboard.html      # Dashboard

│   │   ├── users.html          # User list

│   │   ├── user_detail.html    # User profile

│   │   ├── transactions.html   # Transaction list

│   │   └── logs.html           # Admin logs

│   └── static/                 # Static files (CSS/JS)

│       ├── css/

│       └── js/

│

├── data/                       # Database files (SQLite)

│   └── app.db                  # SQLite database

│

├── logs/                       # Application logs

│   └── app.log

│

├── handlers/                   # Bot handlers

│   ├── i18n_helpers.py         # Internationalization

│   ├── db_helpers.py           # Database helpers

│   └── keyboards.py            # Keyboard builders

│

├── config.py                   # Configuration loader

├── db.py                       # Database models and helpers

├── fsm.py                      # Finite state machine

├── handlers.py                 # Main bot handlers

├── seedream_service.py         # Seedream API wrapper

├── yookassa_service.py         # YooKassa payment service

└── text.py                     # Localization strings (RU/EN)

```

 

---

 

## 📚 API Documentation

 

### Seedream API

 

The bot uses Seedream 4.0 API for image generation:

 

- **Endpoint**: Configured via `SEEDREAM_API` environment variable

- **Methods**:

  - `create_task()` - Create generation task

  - `wait_for_result()` - Poll for results

  - `download_file_bytes()` - Download generated images

 

### Admin Panel API

 

FastAPI admin panel with endpoints:

 

- `GET /admin/login` - Login page

- `POST /admin/login` - Handle login

- `GET /admin/` - Dashboard

- `GET /admin/users` - User list

- `GET /admin/users/{id}` - User details

- `POST /admin/users/{id}/adjust-balance` - Adjust balance

- `GET /admin/transactions` - Transaction list

- `GET /admin/export/users` - Export users

- `GET /admin/export/transactions` - Export transactions

- `GET /admin/logs` - Admin action logs

 

Full API documentation available at: `http://localhost:8001/docs` (when admin panel is running)

 

---

 

## 🚢 Deployment

 

### Production Deployment with systemd (Linux)

 

#### 1. Create Bot Service

 

Create `/etc/systemd/system/seedream-bot.service`:

 

```ini

[Unit]

Description=Seedream Telegram Bot

After=network.target

 

[Service]

Type=simple

User=your_user

WorkingDirectory=/path/to/seedream_bot

Environment="PATH=/path/to/venv/bin"

ExecStart=/path/to/venv/bin/python main.py

Restart=always

RestartSec=10

 

[Install]

WantedBy=multi-user.target

```

 

#### 2. Create Admin Panel Service

 

Create `/etc/systemd/system/seedream-admin.service`:

 

```ini

[Unit]

Description=Seedream Admin Panel

After=network.target

 

[Service]

Type=simple

User=your_user

WorkingDirectory=/path/to/seedream_bot

Environment="PATH=/path/to/venv/bin"

ExecStart=/path/to/venv/bin/python admin_panel.py

Restart=always

RestartSec=10

 

[Install]

WantedBy=multi-user.target

```

 

#### 3. Enable and Start Services

 

```bash

# Reload systemd

sudo systemctl daemon-reload

 

# Enable services

sudo systemctl enable seedream-bot seedream-admin

 

# Start services

sudo systemctl start seedream-bot seedream-admin

 

# Check status

sudo systemctl status seedream-bot

sudo systemctl status seedream-admin

 

# View logs

sudo journalctl -u seedream-bot -f

sudo journalctl -u seedream-admin -f

```

 

### Nginx Reverse Proxy

 

Create `/etc/nginx/sites-available/seedream-admin`:

 

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

 

### Docker Deployment

 

See `LAUNCH_GUIDE.md` for complete Docker setup with docker-compose.

 

---

 

## 🔧 Troubleshooting

 

### Bot Issues

 

**"Invalid bot token"**

- Check `TELEGRAM_BOT_TOKEN` in `.env`

- Ensure no extra spaces or newlines

- Get new token from @BotFather if needed

 

**"Database locked" (SQLite)**

- Only one process can write at a time

- Use PostgreSQL for production

- Ensure only one bot instance is running

 

**"ModuleNotFoundError"**

```bash

pip install -r requirements.txt

```

 

### Admin Panel Issues

 

**"Port 8001 already in use"**

```bash

# Find and kill process

lsof -ti:8001 | xargs kill

 

# Or use different port

ADMIN_PORT=8002 python admin_panel.py

```

 

**"Cannot login to admin panel"**

- Recreate admin user: `python create_admin.py`

- Check `ADMIN_SECRET_KEY` is set in `.env`

- Clear browser cookies

 

**"Static directory error"**

- Pull latest code: `git pull`

- The directory will be created automatically

 

### Payment Issues

 

**YooKassa payments not working**

- Check `YOOKASSA_SHOP_ID` and `YOOKASSA_SECRET_KEY`

- Verify credentials in YooKassa dashboard

- Check logs for API errors

 

**Telegram Stars not working**

- Ensure bot has payment enabled

- Check Telegram bot settings

- Verify payload format

 

---

 

## 📖 Additional Documentation

 

- **[LAUNCH_GUIDE.md](LAUNCH_GUIDE.md)** - Comprehensive launch instructions

- **[ADMIN_PANEL_README.md](ADMIN_PANEL_README.md)** - Admin panel documentation

- **[YOOKASSA_SETUP.md](YOOKASSA_SETUP.md)** - YooKassa configuration (if exists)

 

---

 

## 🤝 Contributing

 

Contributions are welcome! Please feel free to submit a Pull Request.

 

1. Fork the repository

2. Create your feature branch (`git checkout -b feature/AmazingFeature`)

3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)

4. Push to the branch (`git push origin feature/AmazingFeature`)

5. Open a Pull Request

 

---

 

## 📝 License

 

This project is licensed under the MIT License - see the LICENSE file for details.

 

---

 

## 👥 Authors

 

- **Your Name** - Initial work

 

---

 

## 🙏 Acknowledgments

 

- [aiogram](https://github.com/aiogram/aiogram) - Telegram Bot framework

- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework

- [Bootstrap](https://getbootstrap.com/) - UI framework

- Seedream team for the AI generation API

 

---

 

## 📞 Support

 

For support, email your-email@example.com or open an issue on GitHub.

 

---

 

<div align="center">

 

**Made with ❤️ for the Seedream community**

 

⭐ Star this repo if you find it helpful!

 

</div>
