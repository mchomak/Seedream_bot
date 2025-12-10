# Seedream Bot - Admin Panel Documentation

## Overview

Comprehensive web-based admin panel for managing the Seedream Telegram bot. Built with FastAPI, Bootstrap 5, and SQLAlchemy.

## Features

### ✅ Implemented

#### 1. **Authentication & Authorization**
- Login/logout system with session management
- Password hashing with bcrypt
- Admin user roles (active/superuser)
- Last login tracking

#### 2. **User Management**
- Search users by Telegram ID or username
- View complete user profiles:
  - Telegram ID, username, language
  - Registration date and last seen
  - Premium status
  - Credit balance
- Manual balance adjustment with reason tracking
- Transaction history per user
- Generation history per user
- Pagination (50 users per page)

#### 3. **Financial Management**
- Transaction list with filters:
  - Filter by user ID
  - Filter by status (succeeded, pending, failed, canceled)
  - Pagination support
- Transaction details:
  - Amount, currency, kind, status
  - Provider (telegram_stars, yookassa)
  - External ID for tracking
  - Timestamps
- CSV export of all transactions

#### 4. **Analytics Dashboard**
- **Key Metrics:**
  - Total users
  - Active users (last 30 days)
  - Total revenue
  - Average check
  - Total generations
  - Successful generations
  - Success rate (%)

- **Recent Activity:**
  - Last 10 transactions
  - Last 10 registered users

#### 5. **Admin Action Logs**
- Complete audit trail of admin actions
- Logged actions:
  - User balance adjustments
  - Any manual interventions
- Log details:
  - Admin ID
  - Action type
  - Target (type and ID)
  - JSON details
  - IP address
  - Timestamp

#### 6. **Export Functionality**
- Export users to CSV
- Export transactions to CSV
- Downloadable reports

## Installation

### 1. Install Dependencies

```bash
pip install fastapi uvicorn passlib[bcrypt] python-multipart jinja2
```

### 2. Configure Environment Variables

Add to your `.env` file:

```env
# Admin Panel Configuration
ADMIN_SECRET_KEY=your_random_secret_key_at_least_32_characters
ADMIN_PORT=8001
```

Generate a secure secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Run Database Migrations

The admin panel uses the same database as the bot. Tables will be created automatically on first run.

### 4. Create First Admin User

Run the admin creation script:

```bash
python create_admin.py
```

Follow the prompts:
- Enter username
- Enter email (optional)
- Enter password (min 8 characters)
- Confirm password

Example:
```
Enter admin username: admin
Enter admin email (optional): admin@example.com
Enter admin password: ********
Confirm password: ********

✓ Admin user created successfully!
Username: admin
Email: admin@example.com
Superuser: Yes
```

### 5. Start the Admin Panel

```bash
python admin_panel.py
```

Or with uvicorn directly:
```bash
uvicorn admin_panel:app --host 0.0.0.0 --port 8001 --reload
```

The panel will be available at: `http://localhost:8001/admin/login`

## Usage Guide

### Login

1. Navigate to `http://localhost:8001/admin/login`
2. Enter your admin username and password
3. Click "Login"

### Dashboard

The dashboard shows:
- Key performance metrics
- Recent transactions
- Recent user registrations

### Managing Users

1. Click "Users" in the sidebar
2. Use the search box to find users by ID or username
3. Click "View" on any user to see details
4. To adjust balance:
   - Enter amount (positive to add, negative to deduct)
   - Enter reason
   - Click "Adjust Balance"

### Viewing Transactions

1. Click "Transactions" in the sidebar
2. Use filters to narrow down results:
   - User ID
   - Status
3. Click page numbers to navigate

### Exporting Data

- Click "Export Users CSV" in the sidebar to download all users
- Click "Export Transactions CSV" to download all transactions
- Files open in Excel/Google Sheets

### Viewing Admin Logs

1. Click "Admin Logs" in the sidebar
2. See all administrative actions
3. Click "View" on any log to see JSON details

### Logout

Click "Logout" in the sidebar to end your session

## Security

### Best Practices

1. **Strong Passwords**
   - Use passwords with at least 12 characters
   - Mix uppercase, lowercase, numbers, symbols

2. **Secret Key**
   - Generate a unique, random secret key
   - Never commit the secret key to git
   - Store in `.env` file only

3. **Access Control**
   - Only create admin accounts for trusted personnel
   - Use the `is_active` flag to disable accounts
   - Review admin logs regularly

4. **HTTPS**
   - In production, always use HTTPS
   - Use a reverse proxy (nginx, Caddy)

5. **Network Security**
   - Restrict admin panel access by IP if possible
   - Use firewall rules
   - Consider VPN access for sensitive environments

### Reverse Proxy Setup (nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name admin.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Database Schema

### AdminUser Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| username | String(64) | Unique username |
| email | String(256) | Email (optional) |
| password_hash | String(256) | Bcrypt hashed password |
| is_active | Boolean | Account active status |
| is_superuser | Boolean | Superuser privileges |
| last_login | DateTime | Last login timestamp |
| created_at | DateTime | Account creation |
| updated_at | DateTime | Last update |

### AdminActionLog Table

| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| admin_id | Integer | Foreign key to AdminUser |
| action | String(128) | Action name |
| target_type | String(64) | Target entity type |
| target_id | String(128) | Target entity ID |
| details | JSONB | Additional JSON data |
| ip_address | String(64) | Client IP address |
| created_at | DateTime | Action timestamp |

## API Endpoints

### Authentication
- `GET /admin/login` - Show login page
- `POST /admin/login` - Handle login
- `GET /admin/logout` - Logout

### Dashboard & Analytics
- `GET /admin/` - Main dashboard

### User Management
- `GET /admin/users` - List users (with search & pagination)
- `GET /admin/users/{user_id}` - User details
- `POST /admin/users/{user_id}/adjust-balance` - Adjust user balance

### Financial
- `GET /admin/transactions` - List transactions (with filters)

### Export
- `GET /admin/export/users` - Export users CSV
- `GET /admin/export/transactions` - Export transactions CSV

### Logs
- `GET /admin/logs` - Admin action logs

## Troubleshooting

### Cannot Login

**Issue:** "Invalid username or password"

**Solutions:**
1. Verify username is correct (case-sensitive)
2. Recreate admin user: `python create_admin.py`
3. Check database connection
4. Verify user is active:
   ```sql
   SELECT * FROM admin_users WHERE username = 'your_username';
   ```

### Permission Denied

**Issue:** Getting redirected to login

**Solutions:**
1. Clear browser cookies
2. Check session middleware is working
3. Verify `ADMIN_SECRET_KEY` is set

### Database Errors

**Issue:** Table doesn't exist

**Solutions:**
1. Run migrations or restart the bot once to create tables
2. Check `DATABASE_URL` is correct
3. Verify database permissions

### Port Already in Use

**Issue:** Port 8001 already in use

**Solutions:**
1. Change port in `.env`: `ADMIN_PORT=8002`
2. Kill existing process: `lsof -ti:8001 | xargs kill`
3. Use different port: `uvicorn admin_panel:app --port 8002`

## Development

### File Structure

```
Seedream_bot/
├── admin_panel.py              # Main FastAPI application
├── create_admin.py             # Admin user creation script
├── admin/
│   ├── templates/              # Jinja2 HTML templates
│   │   ├── base.html           # Base layout
│   │   ├── login.html          # Login page
│   │   ├── dashboard.html      # Dashboard
│   │   ├── users.html          # User list
│   │   ├── user_detail.html    # User details
│   │   ├── transactions.html   # Transactions
│   │   └── logs.html           # Admin logs
│   └── static/                 # Static files (CSS/JS)
│       ├── css/
│       └── js/
└── db.py                       # Database models (includes AdminUser, AdminActionLog)
```

### Adding New Features

1. **Add Route:**
   ```python
   @app.get("/admin/new-feature")
   async def new_feature(request: Request, admin: AdminUser = Depends(require_admin)):
       return templates.TemplateResponse("new_feature.html", {"request": request, "admin": admin})
   ```

2. **Create Template:**
   ```html
   {% extends "base.html" %}
   {% block content %}
   <!-- Your content here -->
   {% endblock %}
   ```

3. **Add to Sidebar:**
   Edit `admin/templates/base.html` and add menu item

### Running Tests

```bash
# Install pytest
pip install pytest pytest-asyncio httpx

# Run tests
pytest test_admin_panel.py
```

## Future Enhancements

### Planned Features (Not Yet Implemented)

- ❌ Password reset functionality
- ❌ Mass user notifications
- ❌ Tariff configuration UI
- ❌ Split testing dashboard
- ❌ Advanced analytics charts
- ❌ ARPU/ARPPU/LTV calculations
- ❌ Conversion funnel visualization
- ❌ PDF export for reports
- ❌ API access for external tools
- ❌ Automated backups UI
- ❌ Multi-admin management
- ❌ Role-based permissions

To add these features, extend `admin_panel.py` with new routes and create corresponding templates.

## Support

For issues or questions:
1. Check this documentation
2. Review admin logs for errors
3. Check application logs
4. Open an issue on the project repository

## License

Same as the main Seedream bot project.
