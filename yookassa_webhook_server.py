"""
YooKassa Webhook Server

This is a standalone FastAPI server to handle YooKassa payment notifications.
It should be run separately from the main bot and exposed to the internet.

Installation:
    pip install fastapi uvicorn

Usage:
    python yookassa_webhook_server.py

Or with uvicorn directly:
    uvicorn yookassa_webhook_server:app --host 0.0.0.0 --port 8000

Environment variables required:
    - DATABASE_URL: Same as bot's database URL
    - YOOKASSA_SHOP_ID: Your YooKassa Shop ID
    - YOOKASSA_SECRET_KEY: Your YooKassa Secret Key
    - WEBHOOK_SECRET: Secret token to verify webhook authenticity (optional but recommended)

YooKassa Configuration:
    1. Go to YooKassa merchant dashboard
    2. Navigate to Settings > Notifications
    3. Set webhook URL to: https://your-domain.com/yookassa/webhook
    4. Enable notifications for: payment.succeeded, payment.canceled
"""

import asyncio
import os
from typing import Dict, Any

try:
    from fastapi import FastAPI, Request, HTTPException, Header
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    print("ERROR: FastAPI not installed. Install with: pip install fastapi uvicorn")
    exit(1)

from loguru import logger
from db import Database
from yookassa_payment import YooKassaPay
from config import load_env


# Initialize FastAPI app
app = FastAPI(
    title="YooKassa Webhook Handler",
    description="Handles payment notifications from YooKassa",
    version="1.0.0"
)

# Global variables (initialized on startup)
db: Database = None
yookassa: YooKassaPay = None
webhook_secret: str = None


@app.on_event("startup")
async def startup_event():
    """Initialize database and YooKassa service on startup."""
    global db, yookassa, webhook_secret

    # Load environment variables
    settings = load_env()

    # Initialize database
    db = await Database.create(settings.database_url)
    logger.info(f"Database initialized: {settings.database_url}")

    # Initialize YooKassa payment service
    yookassa = YooKassaPay(db)

    if not yookassa.enabled:
        logger.warning("YooKassa service is not enabled. Check your configuration.")
    else:
        logger.info("YooKassa service initialized successfully")

    # Load webhook secret for verification (optional)
    webhook_secret = os.getenv("YOOKASSA_WEBHOOK_SECRET")
    if webhook_secret:
        logger.info("Webhook secret verification enabled")
    else:
        logger.warning("Webhook secret not set. Notifications will not be verified.")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global db
    if db:
        await db.close()
        logger.info("Database connection closed")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "YooKassa Webhook Handler",
        "yookassa_enabled": yookassa.enabled if yookassa else False,
    }


@app.get("/health")
async def health_check():
    """Detailed health check endpoint."""
    return {
        "status": "healthy",
        "database": "connected" if db else "not connected",
        "yookassa": "enabled" if (yookassa and yookassa.enabled) else "disabled",
    }


@app.post("/yookassa/webhook")
async def yookassa_webhook(
    request: Request,
    x_webhook_secret: str = Header(None, alias="X-Webhook-Secret")
):
    """
    Handle YooKassa payment notifications.

    YooKassa sends POST requests to this endpoint with payment status updates.
    """
    try:
        # Verify webhook secret if configured
        if webhook_secret and x_webhook_secret != webhook_secret:
            logger.warning(f"Invalid webhook secret received: {x_webhook_secret}")
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

        # Parse JSON body
        try:
            notification_data: Dict[str, Any] = await request.json()
        except Exception as e:
            logger.error(f"Failed to parse webhook JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON")

        logger.info(f"Received YooKassa notification: {notification_data.get('event')}")

        # Validate YooKassa service is available
        if not yookassa or not yookassa.enabled:
            logger.error("YooKassa service not available")
            raise HTTPException(status_code=500, detail="YooKassa service not configured")

        # Process the notification
        success = await yookassa.handle_webhook_notification(notification_data)

        if success:
            logger.info(f"Successfully processed YooKassa notification")
            return JSONResponse(
                status_code=200,
                content={"status": "ok", "message": "Notification processed"}
            )
        else:
            logger.error("Failed to process YooKassa notification")
            raise HTTPException(status_code=500, detail="Failed to process notification")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/yookassa/test")
async def test_webhook(request: Request):
    """
    Test endpoint to simulate YooKassa webhook notifications.
    Useful for development and testing.

    Example payload:
    {
        "event": "payment.succeeded",
        "object": {
            "id": "test-payment-id",
            "status": "succeeded",
            "paid": true,
            "amount": {
                "value": "100.00",
                "currency": "RUB"
            },
            "metadata": {
                "user_id": "123456789",
                "telegram_username": "testuser"
            }
        }
    }
    """
    try:
        notification_data = await request.json()
        logger.info(f"Test webhook received: {notification_data}")

        if not yookassa or not yookassa.enabled:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "YooKassa service not configured"}
            )

        success = await yookassa.handle_webhook_notification(notification_data)

        return JSONResponse(
            status_code=200,
            content={
                "status": "ok" if success else "error",
                "message": "Test notification processed" if success else "Processing failed"
            }
        )
    except Exception as e:
        logger.exception(f"Test webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


if __name__ == "__main__":
    # Run the webhook server
    port = int(os.getenv("WEBHOOK_PORT", "8000"))
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")

    logger.info(f"Starting YooKassa webhook server on {host}:{port}")

    uvicorn.run(
        "yookassa_webhook_server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
