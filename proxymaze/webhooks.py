"""Webhook delivery system with retry logic"""
import aiohttp
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from models import WebhookDelivery, Webhook
from database import SessionLocal
import json


class WebhookDeliveryService:
    MAX_RETRIES = 5
    RETRY_DELAY = 5  # seconds
    DELIVERY_TIMEOUT = 60  # seconds
    
    async def process_pending_deliveries(self, db: Session):
        """Process pending webhook deliveries with retries"""
        while True:
            pending = db.query(WebhookDelivery).filter_by(status="pending").all()
            
            for delivery in pending:
                webhook = db.query(Webhook).filter_by(id=delivery.webhook_id).first()
                if not webhook:
                    delivery.status = "failed"
                    db.commit()
                    continue
                
                success = await self._send_webhook(webhook.url, delivery.payload)
                
                if success:
                    delivery.status = "delivered"
                    delivery.delivered_at = datetime.utcnow()
                else:
                    delivery.attempts += 1
                    delivery.last_attempted_at = datetime.utcnow()
                    
                    if delivery.attempts >= self.MAX_RETRIES:
                        delivery.status = "failed"
                    else:
                        # Will retry on next iteration
                        pass
                
                db.commit()
            
            await asyncio.sleep(self.RETRY_DELAY)
    
    async def _send_webhook(self, url: str, payload: str) -> bool:
        """Send webhook with proper headers"""
        try:
            timeout = aiohttp.ClientTimeout(total=self.DELIVERY_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    # Success if 2xx
                    if 200 <= resp.status < 300:
                        return True
                    # Retry on transient errors (5xx)
                    if resp.status in [500, 502, 503, 504]:
                        return False
                    # Permanent failure on other errors
                    return False
        except (asyncio.TimeoutError, aiohttp.ClientError, Exception):
            # Transient error - retry
            return False


webhook_service = WebhookDeliveryService()
