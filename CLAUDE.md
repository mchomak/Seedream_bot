# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Seedream Bot is a Telegram bot that lets users upload clothing photos and generate AI model images via the Seedream API. It includes a FastAPI admin panel for user management, analytics, and payment administration.

## Running the Project

**Setup:**
```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # Then fill in required values
mkdir -p data
```

**Launch (two separate terminals):**
```bash
python main.py               # Telegram bot (aiogram polling)
python admin_panel.py        # Admin panel at http://localhost:8001/admin/login
```

**Create first admin user:**
```bash
python scripts/create_admin.py
```

**Docker (full stack with PostgreSQL + Redis):**
```bash
docker-compose up
```

There are no automated tests or linters configured.

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` (dev) or `postgresql+asyncpg://...` (prod) |
| `SEEDREAM_API` | Seedream image generation API key |
| `YOOKASSA_SHOP_ID` / `YOOKASSA_SECRET_KEY` | Russian payment processor (optional) |
| `ADMIN_SECRET_KEY` | 32-char secret for admin session signing |
| `REDIS_URL` | FSM state storage; falls back to in-memory if absent |

## Architecture

### Main Entry Points
- [main.py](main.py) — starts the aiogram bot in polling mode, registers handlers from `utils/handlers.py`
- [admin_panel.py](admin_panel.py) — FastAPI app (~2850 lines) serving the admin web UI via Jinja2 templates

### Core Modules (`utils/`)
- [utils/handlers.py](utils/handlers.py) (~5640 lines) — all bot logic: FSM state machine, command handlers, callback query handlers, keyboard responses, payment flows
- [utils/db.py](utils/db.py) — SQLAlchemy 2.0 async ORM models; tables are auto-created on startup (no migrations)
- [utils/fsm.py](utils/fsm.py) — aiogram `StatesGroup` definitions for the multi-step generation flow (Upload → Customize → Review → etc.)
- [utils/seedream_service.py](utils/seedream_service.py) — HTTP client for the Seedream image generation API with retry logic and proxy support
- [utils/config.py](utils/config.py) — app settings, generation scenario credit costs, UI label mappings
- [utils/localization.py](utils/localization.py) — CSV-based i18n; primary language is Russian with English fallback; phrases loaded from [locales/phrases.csv](locales/phrases.csv)
- [utils/yookassa_service.py](utils/yookassa_service.py) — YooKassa payment API integration

### Modular Handlers (`handlers_func/`)
- [handlers_func/keyboards.py](handlers_func/keyboards.py) — all aiogram `InlineKeyboardMarkup` and `ReplyKeyboardMarkup` builders
- [handlers_func/db_helpers.py](handlers_func/db_helpers.py) — shared DB query helpers used by handlers
- [handlers_func/i18n_helpers.py](handlers_func/i18n_helpers.py) — localization helpers wrapping `localization.py`

### Admin Panel (`admin/templates/`)
Jinja2 templates for: dashboard, users, transactions, analytics, conversions, reports, settings (tariffs, scenario prices, system settings), broadcast, and logs.

## Database Schema (key tables)

- `users` — Telegram user ID, credit balance, A/B group, frozen status
- `transactions` — payments (Stars or YooKassa), status, external payment IDs
- `generations` — image generation requests with JSON params and credit cost
- `generated_images` — result URLs with `base`/`variant` role
- `system_settings` — key/value config pairs (free generation limit, etc.)
- `tariff_packages` — credit purchase tiers with optional A/B group targeting
- `scenario_prices` — per-action credit costs (configurable from admin panel)
- `admin_users` + `admin_action_logs` — admin accounts and audit trail
- `broadcast_messages` — mass notification records

## Generation Flow (FSM)

1. User uploads clothing image → stored in `data/img/`
2. User selects: background, gender, hair, age, style, aspect ratio (each a separate FSM state)
3. Bot calls Seedream API → polls for result → saves to `data/outputs/`
4. User reviews generated images; credits deducted only on successful generation
5. User can request variants from any approved base image

## Payment Integrations

- **Telegram Stars** — native in-app payments via aiogram's `PreCheckoutQuery` flow
- **YooKassa** — webhook-based; requires a public URL for callbacks
