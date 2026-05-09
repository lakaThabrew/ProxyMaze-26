"""Alert management and detection"""
from datetime import datetime
from sqlalchemy.orm import Session
from models import Proxy, Alert, AlertStatus, ProxyStatus, WebhookDelivery, Integration
from database import SessionLocal
import json
import uuid
import asyncio
from typing import List


class AlertManager:
    THRESHOLD = 0.20
    
    async def evaluate_alerts(self, db: Session):
        """Evaluate alert conditions and manage alert lifecycle"""
        proxies = db.query(Proxy).all()
        
        if not proxies:
            return
        
        total = len(proxies)
        failed = sum(1 for p in proxies if p.status == ProxyStatus.DOWN)
        failure_rate = failed / total if total > 0 else 0.0
        
        active_alert = db.query(Alert).filter_by(status=AlertStatus.ACTIVE).first()
        
        if failure_rate >= self.THRESHOLD:
            # BREACH: Alert should be active
            if not active_alert:
                # Create new alert
                alert_id = f"alert-{uuid.uuid4().hex[:8]}"
                failed_proxy_ids = [p.id for p in proxies if p.status == ProxyStatus.DOWN]
                
                alert = Alert(
                    alert_id=alert_id,
                    status=AlertStatus.ACTIVE,
                    failure_rate=failure_rate,
                    total_proxies=total,
                    failed_proxies=failed,
                    failed_proxy_ids=json.dumps(failed_proxy_ids),
                    threshold=self.THRESHOLD,
                    fired_at=datetime.utcnow(),
                    resolved_at=None,
                    message="Proxy pool failure rate exceeded threshold"
                )
                db.add(alert)
                db.commit()
                
                # Deliver alert.fired events
                await self._deliver_alert_fired(db, alert)
            else:
                # Update active alert with latest state
                failed_proxy_ids = [p.id for p in proxies if p.status == ProxyStatus.DOWN]
                active_alert.failure_rate = failure_rate
                active_alert.failed_proxies = failed
                active_alert.failed_proxy_ids = json.dumps(failed_proxy_ids)
                db.commit()
        else:
            # NO BREACH: Alert should be resolved
            if active_alert:
                # Resolve the alert
                active_alert.status = AlertStatus.RESOLVED
                active_alert.resolved_at = datetime.utcnow()
                db.commit()
                
                # Deliver alert.resolved events
                await self._deliver_alert_resolved(db, active_alert)
    
    async def _deliver_alert_fired(self, db: Session, alert: Alert):
        """Deliver alert.fired webhook events"""
        webhooks = db.query(Integration).all()
        
        payload = {
            "event": "alert.fired",
            "alert_id": alert.alert_id,
            "fired_at": alert.fired_at.isoformat() + "Z",
            "failure_rate": alert.failure_rate,
            "total_proxies": alert.total_proxies,
            "failed_proxies": alert.failed_proxies,
            "failed_proxy_ids": json.loads(alert.failed_proxy_ids),
            "threshold": alert.threshold,
            "message": alert.message
        }
        
        for webhook in webhooks:
            if "alert.fired" in json.loads(webhook.events):
                delivery = WebhookDelivery(
                    webhook_id=webhook.id,
                    alert_id=alert.alert_id,
                    event_type="alert.fired",
                    status="pending",
                    payload=json.dumps(payload)
                )
                db.add(delivery)
        
        db.commit()
    
    async def _deliver_alert_resolved(self, db: Session, alert: Alert):
        """Deliver alert.resolved webhook events"""
        webhooks = db.query(Integration).all()
        
        payload = {
            "event": "alert.resolved",
            "alert_id": alert.alert_id,
            "resolved_at": alert.resolved_at.isoformat() + "Z"
        }
        
        for webhook in webhooks:
            if "alert.resolved" in json.loads(webhook.events):
                delivery = WebhookDelivery(
                    webhook_id=webhook.id,
                    alert_id=alert.alert_id,
                    event_type="alert.resolved",
                    status="pending",
                    payload=json.dumps(payload)
                )
                db.add(delivery)
        
        db.commit()
