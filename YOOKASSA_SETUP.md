# YooKassa Payment Integration Setup Guide

This guide explains how to set up YooKassa payment integration for your Telegram bot.

## Overview

The bot now supports two payment methods:
1. **Telegram Stars** - Native Telegram payment (already implemented)
2. **YooKassa** - Russian payment service supporting bank cards

When users click "Top Up Balance" or use `/buy` command, they will see a menu to choose their preferred payment method.

## Required Credentials

To enable YooKassa payments, you need the following credentials from YooKassa:

### 1. Shop ID (YOOKASSA_SHOP_ID)
- Your merchant account identifier
- Format: 6-digit number (e.g., `123456`)
- Where to find: YooKassa merchant dashboard → Settings → Shop Details

### 2. Secret Key (YOOKASSA_SECRET_KEY)
- API authentication key
- Format: `live_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX` (for production) or `test_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX` (for testing)
- Where to find: YooKassa merchant dashboard → Settings → API Keys
- **Important**: Keep this secret! Never commit it to version control.

### 3. Return URL (YOOKASSA_RETURN_URL)
- URL where users are redirected after payment
- Recommended: Your bot's deep link, e.g., `https://t.me/your_bot_username`
- Alternative: Your website URL

### 4. Webhook Secret (YOOKASSA_WEBHOOK_SECRET) - Optional but Recommended
- Random string to verify webhook authenticity
- Generate a strong random string (32+ characters)
- Example: `7a8f9d3e2c1b4a5d6e7f8a9b0c1d2e3f4a5b6c7d`

## Installation Steps

### Step 1: Install YooKassa SDK

```bash
pip install yookassa
```

### Step 2: Install FastAPI and Uvicorn (for webhook server)

```bash
pip install fastapi uvicorn
```

### Step 3: Configure Environment Variables

Add the following to your `.env` file:

```env
# YooKassa Payment Configuration
YOOKASSA_SHOP_ID=your_shop_id_here
YOOKASSA_SECRET_KEY=live_your_secret_key_here
YOOKASSA_RETURN_URL=https://t.me/your_bot_username
YOOKASSA_WEBHOOK_SECRET=your_random_secret_string_here

# YooKassa Webhook Server
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
```

### Step 4: Start the Webhook Server

The YooKassa webhook server handles payment notifications from YooKassa. It must be running and accessible from the internet.

**Option A: Run directly**
```bash
python yookassa_webhook_server.py
```

**Option B: Run with uvicorn**
```bash
uvicorn yookassa_webhook_server:app --host 0.0.0.0 --port 8000
```

**Option C: Run with systemd (production)**

Create `/etc/systemd/system/yookassa-webhook.service`:
```ini
[Unit]
Description=YooKassa Webhook Server
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Seedream_bot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python yookassa_webhook_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable yookassa-webhook
sudo systemctl start yookassa-webhook
```

### Step 5: Expose Webhook Server to Internet

The webhook server must be accessible from YooKassa servers. Options:

**Option A: Nginx Reverse Proxy (Recommended)**

Add to nginx config:
```nginx
location /yookassa/ {
    proxy_pass http://127.0.0.1:8000/yookassa/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

**Option B: Direct Exposure (Not Recommended)**
```bash
uvicorn yookassa_webhook_server:app --host 0.0.0.0 --port 8000
```

**Option C: Tunneling (Development Only)**

Using ngrok:
```bash
ngrok http 8000
```

### Step 6: Configure YooKassa Webhook URL

1. Go to [YooKassa Merchant Dashboard](https://yookassa.ru/my)
2. Navigate to: **Settings** → **Notifications** → **HTTP notifications**
3. Set webhook URL: `https://your-domain.com/yookassa/webhook`
4. Add custom header (if using webhook secret):
   - Header name: `X-Webhook-Secret`
   - Header value: `your_random_secret_string_here` (same as in .env)
5. Enable notifications for:
   - ✅ `payment.succeeded` - Payment successful
   - ✅ `payment.canceled` - Payment canceled/failed
6. Save settings

### Step 7: Test the Integration

#### Test Webhook Server Health
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "yookassa": "enabled"
}
```

#### Test Payment Flow

1. Start your Telegram bot
2. Send `/buy` command
3. Choose "💳 Bank Card (YooKassa)"
4. Click the payment link
5. Complete test payment
6. Check webhook server logs for notification

#### Test Webhook Endpoint

```bash
curl -X POST http://localhost:8000/yookassa/test \
  -H "Content-Type: application/json" \
  -d '{
    "event": "payment.succeeded",
    "object": {
      "id": "test-payment-123",
      "status": "succeeded",
      "paid": true,
      "amount": {
        "value": "100.00",
        "currency": "RUB"
      },
      "metadata": {
        "user_id": "123456789"
      }
    }
  }'
```

## How It Works

### Payment Flow

1. **User initiates payment**
   - User clicks "Top Up Balance" or sends `/buy`
   - Bot shows payment method selection: Stars or YooKassa

2. **YooKassa payment selected**
   - User selects "💳 Bank Card (YooKassa)"
   - Bot creates payment via YooKassa API
   - User receives payment link with inline button

3. **User completes payment**
   - User clicks payment button
   - Redirected to YooKassa payment page
   - Enters card details and confirms payment
   - Redirected to return URL (Telegram bot)

4. **Webhook notification**
   - YooKassa sends notification to webhook server
   - Webhook server verifies and processes notification
   - User balance updated in database
   - Transaction recorded with status "succeeded"

5. **User receives confirmation**
   - User can check balance in "My Account"
   - Credits are available for image generation

### Credit Conversion

Default conversion rate (configurable in `yookassa_payment.py`):
- **1 ruble = 1 credit**

To change this, modify line in `yookassa_payment.py`:
```python
# Example: 1 ruble = 10 credits
credits_to_add = int(amount_rubles) * 10
```

## Troubleshooting

### "YooKassa payment is temporarily unavailable"

**Cause**: YooKassa SDK not installed or credentials not configured

**Solution**:
1. Install SDK: `pip install yookassa`
2. Check `.env` file has correct credentials
3. Restart bot

### Webhook not receiving notifications

**Possible causes**:
1. Webhook server not running
2. Webhook URL not accessible from internet
3. Incorrect webhook URL in YooKassa dashboard
4. Firewall blocking incoming requests

**Solutions**:
- Check server logs: `journalctl -u yookassa-webhook -f`
- Test endpoint: `curl https://your-domain.com/yookassa/webhook`
- Verify YooKassa dashboard webhook URL
- Check nginx/firewall configuration

### Payment successful but balance not updated

**Cause**: Webhook notification not processed correctly

**Solution**:
1. Check webhook server logs for errors
2. Verify database connection
3. Test webhook endpoint manually
4. Check YooKassa dashboard for notification delivery status

### "Invalid webhook secret"

**Cause**: Webhook secret mismatch

**Solution**:
1. Verify `YOOKASSA_WEBHOOK_SECRET` in `.env`
2. Check custom header in YooKassa dashboard matches
3. Restart webhook server after changing secret

## Security Best Practices

1. **Use HTTPS**: Always use HTTPS for webhook URL in production
2. **Set Webhook Secret**: Use strong random secret for webhook verification
3. **Protect Secret Key**: Never commit `YOOKASSA_SECRET_KEY` to git
4. **Use Environment Variables**: Store all credentials in `.env` file
5. **Firewall Rules**: Restrict webhook server access if possible
6. **Monitor Logs**: Regularly check logs for suspicious activity

## Testing Mode

YooKassa provides test credentials for development:

1. Use test secret key: `test_XXXXX...`
2. Use test shop ID from YooKassa dashboard
3. Use test bank cards:
   - Successful payment: `5555 5555 5555 4444`
   - Failed payment: `5555 5555 5555 5557`
   - Expiry: any future date
   - CVC: any 3 digits

**Important**: Test mode does not process real payments.

## Additional Resources

- [YooKassa Documentation](https://yookassa.ru/developers)
- [YooKassa Python SDK](https://github.com/yoomoney/yookassa-sdk-python)
- [YooKassa API Reference](https://yookassa.ru/developers/api)
- [YooKassa Merchant Dashboard](https://yookassa.ru/my)

## Support

If you encounter issues:
1. Check webhook server logs
2. Check bot logs
3. Verify YooKassa dashboard for notification delivery
4. Test with YooKassa test credentials first
5. Contact YooKassa support for payment-specific issues
