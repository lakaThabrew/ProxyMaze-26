"""ProxyMaze - Real-time proxy monitoring service"""
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session
from datetime import datetime
from models import (
    Proxy, ProxyStatus, Alert, AlertStatus, Webhook, Config, 
    Integration, ProxyCheck
)
from database import init_db, get_db, SessionLocal
import json
import uuid
import asyncio
import aiohttp
from typing import Optional

app = FastAPI(title="ProxyMaze", version="1.0.0")

# Background task references
monitoring_task = None
webhook_task = None
THRESHOLD = 0.20


# ============================================================================
# Background Monitoring Service
# ============================================================================

async def run_proxy_monitoring():
    """Continuously monitor proxies"""
    while True:
        db = SessionLocal()
        try:
            config = db.query(Config).filter_by(id="default").first()
            if not config:
                config = Config(id="default")
                db.add(config)
                db.commit()
            
            interval = config.check_interval_seconds
            timeout_ms = config.request_timeout_ms
            
            proxies = db.query(Proxy).all()
            
            # Check all proxies concurrently
            tasks = []
            for proxy in proxies:
                tasks.append(check_proxy_health(proxy.url, timeout_ms / 1000.0))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Update proxy status
                for proxy, result in zip(proxies, results):
                    is_up = isinstance(result, bool) and result
                    new_status = ProxyStatus.UP if is_up else ProxyStatus.DOWN
                    
                    # Track consecutive failures
                    if new_status == ProxyStatus.DOWN:
                        proxy.consecutive_failures += 1
                    else:
                        proxy.consecutive_failures = 0
                    
                    # Update counters
                    proxy.total_checks += 1
                    if is_up:
                        proxy.successful_checks += 1
                    
                    proxy.status = new_status
                    proxy.last_checked_at = datetime.utcnow()
                    
                    # Record check history
                    check = ProxyCheck(
                        proxy_id=proxy.id,
                        status=new_status,
                        checked_at=datetime.utcnow()
                    )
                    db.add(check)
                
                db.commit()
                
                # Evaluate alerts
                await evaluate_alerts(db)
            
            await asyncio.sleep(interval)
        except Exception as e:
            print(f"Monitoring error: {e}")
            await asyncio.sleep(5)
        finally:
            db.close()


async def check_proxy_health(url: str, timeout: float) -> bool:
    """Check if proxy is accessible"""
    try:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            async with session.get(url, allow_redirects=True) as resp:
                return 200 <= resp.status < 300
    except Exception:
        return False


async def evaluate_alerts(db: Session):
    """Evaluate alert conditions"""
    proxies = db.query(Proxy).all()
    
    if not proxies:
        return
    
    total = len(proxies)
    failed = sum(1 for p in proxies if p.status == ProxyStatus.DOWN)
    failure_rate = failed / total if total > 0 else 0.0
    failed_proxy_ids = [p.id for p in proxies if p.status == ProxyStatus.DOWN]
    
    active_alert = db.query(Alert).filter_by(status=AlertStatus.ACTIVE).first()
    
    if failure_rate >= THRESHOLD:
        # BREACH: Alert should be active
        if not active_alert:
            # Create new alert
            alert_id = f"alert-{uuid.uuid4().hex[:8]}"
            
            alert = Alert(
                alert_id=alert_id,
                status=AlertStatus.ACTIVE,
                failure_rate=failure_rate,
                total_proxies=total,
                failed_proxies=failed,
                failed_proxy_ids=json.dumps(failed_proxy_ids),
                threshold=THRESHOLD,
                fired_at=datetime.utcnow(),
                resolved_at=None,
                message="Proxy pool failure rate exceeded threshold"
            )
            db.add(alert)
            db.commit()
            
            # Queue alert.fired events
            await queue_webhook_deliveries(db, alert, "alert.fired")
        else:
            # Update active alert
            active_alert.failure_rate = failure_rate
            active_alert.failed_proxies = failed
            active_alert.failed_proxy_ids = json.dumps(failed_proxy_ids)
            db.commit()
    else:
        # NO BREACH: Alert should be resolved
        if active_alert:
            active_alert.status = AlertStatus.RESOLVED
            active_alert.resolved_at = datetime.utcnow()
            db.commit()
            
            # Queue alert.resolved events
            await queue_webhook_deliveries(db, active_alert, "alert.resolved")


async def queue_webhook_deliveries(db: Session, alert: Alert, event_type: str):
    """Queue webhook deliveries for alert event"""
    from models import WebhookDelivery
    
    webhooks = db.query(Integration).all()
    
    if event_type == "alert.fired":
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
            events = json.loads(webhook.events)
            if "alert.fired" in events:
                delivery = WebhookDelivery(
                    webhook_id=webhook.id,
                    alert_id=alert.alert_id,
                    event_type="alert.fired",
                    status="pending",
                    payload=json.dumps(payload)
                )
                db.add(delivery)
    
    elif event_type == "alert.resolved":
        payload = {
            "event": "alert.resolved",
            "alert_id": alert.alert_id,
            "resolved_at": alert.resolved_at.isoformat() + "Z"
        }
        
        for webhook in webhooks:
            events = json.loads(webhook.events)
            if "alert.resolved" in events:
                delivery = WebhookDelivery(
                    webhook_id=webhook.id,
                    alert_id=alert.alert_id,
                    event_type="alert.resolved",
                    status="pending",
                    payload=json.dumps(payload)
                )
                db.add(delivery)
    
    db.commit()


async def process_webhook_deliveries():
    """Process pending webhook deliveries with retries"""
    while True:
        db = SessionLocal()
        try:
            from models import WebhookDelivery
            
            pending = db.query(WebhookDelivery).filter_by(status="pending").all()
            
            for delivery in pending:
                webhook = db.query(Webhook).filter_by(id=delivery.webhook_id).first()
                if not webhook:
                    delivery.status = "failed"
                    db.commit()
                    continue
                
                success = await send_webhook(webhook.url, delivery.payload)
                
                if success:
                    delivery.status = "delivered"
                    delivery.delivered_at = datetime.utcnow()
                else:
                    delivery.attempts += 1
                    delivery.last_attempted_at = datetime.utcnow()
                    
                    if delivery.attempts >= 5:
                        delivery.status = "failed"
                
                db.commit()
            
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Webhook delivery error: {e}")
            await asyncio.sleep(5)
        finally:
            db.close()


async def send_webhook(url: str, payload: str) -> bool:
    """Send webhook with proper headers and error handling"""
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                data=payload,
                headers={"Content-Type": "application/json"}
            ) as resp:
                if 200 <= resp.status < 300:
                    return True
                # Retry on transient errors
                if resp.status in [500, 502, 503, 504]:
                    return False
                return False
    except Exception:
        return False


# ============================================================================
# Startup and Shutdown
# ============================================================================

@app.on_event("startup")
async def startup():
    """Initialize database and start background tasks"""
    global monitoring_task, webhook_task
    
    init_db()
    
    # Start background monitoring
    monitoring_task = asyncio.create_task(run_proxy_monitoring())
    webhook_task = asyncio.create_task(process_webhook_deliveries())


# ============================================================================
# CHAPTER 01: Proof of Life
# ============================================================================

@app.get("/health")
async def health():
    """Service health check"""
    return {"status": "ok"}


# ============================================================================
# CHAPTER 02-03: Configuration Management
# ============================================================================

@app.post("/config")
async def set_config(config_data: dict, db: Session = Depends(get_db)):
    """Set runtime monitoring configuration"""
    config = db.query(Config).filter_by(id="default").first()
    if not config:
        config = Config(id="default")
    
    if "check_interval_seconds" in config_data:
        config.check_interval_seconds = config_data["check_interval_seconds"]
    if "request_timeout_ms" in config_data:
        config.request_timeout_ms = config_data["request_timeout_ms"]
    
    config.updated_at = datetime.utcnow()
    db.add(config)
    db.commit()
    
    return {"status": "ok"}


@app.get("/config")
async def get_config(db: Session = Depends(get_db)):
    """Get current runtime configuration"""
    config = db.query(Config).filter_by(id="default").first()
    if not config:
        config = Config(id="default")
        db.add(config)
        db.commit()
    
    return {
        "check_interval_seconds": config.check_interval_seconds,
        "request_timeout_ms": config.request_timeout_ms
    }


# ============================================================================
# CHAPTER 04: Proxy Pool Management
# ============================================================================

def extract_proxy_id(url: str) -> str:
    """Extract proxy ID from URL (final path segment)"""
    return url.rstrip("/").split("/")[-1]


@app.post("/proxies", status_code=201)
async def add_proxies(data: dict, db: Session = Depends(get_db)):
    """Load proxy URLs into monitoring pool"""
    proxies_list = data.get("proxies", [])
    replace = data.get("replace", False)
    
    if replace:
        # Clear existing proxies but keep alerts
        db.query(Proxy).delete()
        db.commit()
    
    accepted = 0
    created_proxies = []
    
    for url in proxies_list:
        proxy_id = extract_proxy_id(url)
        
        # Check if already exists
        existing = db.query(Proxy).filter_by(id=proxy_id).first()
        if not existing:
            proxy = Proxy(
                id=proxy_id,
                url=url,
                status=ProxyStatus.PENDING
            )
            db.add(proxy)
            accepted += 1
        else:
            existing.url = url
            accepted += 1
        
        created_proxies.append({
            "id": proxy_id,
            "url": url,
            "status": ProxyStatus.PENDING
        })
    
    db.commit()
    
    return {
        "accepted": accepted,
        "proxies": created_proxies
    }


# ============================================================================
# CHAPTER 05: Pool Status
# ============================================================================

@app.get("/proxies")
async def get_proxies(db: Session = Depends(get_db)):
    """Get current pool status and per-proxy state"""
    proxies = db.query(Proxy).all()
    
    total = len(proxies)
    up = sum(1 for p in proxies if p.status == ProxyStatus.UP)
    down = sum(1 for p in proxies if p.status == ProxyStatus.DOWN)
    failure_rate = down / total if total > 0 else 0.0
    
    proxies_data = []
    for p in proxies:
        proxies_data.append({
            "id": p.id,
            "url": p.url,
            "status": p.status,
            "last_checked_at": p.last_checked_at.isoformat() + "Z" if p.last_checked_at else None,
            "consecutive_failures": p.consecutive_failures
        })
    
    return {
        "total": total,
        "up": up,
        "down": down,
        "failure_rate": failure_rate,
        "proxies": proxies_data
    }


# ============================================================================
# CHAPTER 06: Single Proxy Details
# ============================================================================

@app.get("/proxies/{proxy_id}")
async def get_proxy(proxy_id: str, db: Session = Depends(get_db)):
    """Get details for a single proxy"""
    proxy = db.query(Proxy).filter_by(id=proxy_id).first()
    
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    history = db.query(ProxyCheck).filter_by(proxy_id=proxy_id).all()
    history_data = [
        {
            "checked_at": h.checked_at.isoformat() + "Z",
            "status": h.status
        }
        for h in history
    ]
    
    return {
        "id": proxy.id,
        "url": proxy.url,
        "status": proxy.status,
        "last_checked_at": proxy.last_checked_at.isoformat() + "Z" if proxy.last_checked_at else None,
        "consecutive_failures": proxy.consecutive_failures,
        "total_checks": proxy.total_checks,
        "uptime_percentage": round(proxy.uptime_percentage(), 1),
        "history": history_data
    }


# ============================================================================
# CHAPTER 07: Proxy History
# ============================================================================

@app.get("/proxies/{proxy_id}/history")
async def get_proxy_history(proxy_id: str, db: Session = Depends(get_db)):
    """Get check history for a single proxy"""
    proxy = db.query(Proxy).filter_by(id=proxy_id).first()
    
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    history = db.query(ProxyCheck).filter_by(proxy_id=proxy_id).all()
    
    return [
        {
            "checked_at": h.checked_at.isoformat() + "Z",
            "status": h.status
        }
        for h in history
    ]


# ============================================================================
# CHAPTER 08: Clear Pool
# ============================================================================

@app.delete("/proxies", status_code=204)
async def delete_proxies(db: Session = Depends(get_db)):
    """Clear proxy pool (alerts remain)"""
    db.query(Proxy).delete()
    db.commit()
    return None


# ============================================================================
# CHAPTER 09: Alerts Archive
# ============================================================================

@app.get("/alerts")
async def get_alerts(db: Session = Depends(get_db)):
    """Get all alerts (active and resolved)"""
    alerts = db.query(Alert).all()
    
    alerts_data = []
    for alert in alerts:
        failed_proxy_ids = json.loads(alert.failed_proxy_ids)
        alerts_data.append({
            "alert_id": alert.alert_id,
            "status": alert.status,
            "failure_rate": alert.failure_rate,
            "total_proxies": alert.total_proxies,
            "failed_proxies": alert.failed_proxies,
            "failed_proxy_ids": failed_proxy_ids,
            "threshold": alert.threshold,
            "fired_at": alert.fired_at.isoformat() + "Z",
            "resolved_at": alert.resolved_at.isoformat() + "Z" if alert.resolved_at else None,
            "message": alert.message
        })
    
    return alerts_data


# ============================================================================
# CHAPTER 10: Webhook Registration (Basic)
# ============================================================================

@app.post("/webhooks", status_code=201)
async def register_webhook(data: dict, db: Session = Depends(get_db)):
    """Register URL to receive alert webhook notifications"""
    url = data.get("url")
    
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    webhook_id = f"wh-{uuid.uuid4().hex[:8]}"
    
    webhook = Webhook(webhook_id=webhook_id, url=url)
    db.add(webhook)
    db.commit()
    
    return {
        "webhook_id": webhook_id,
        "url": url
    }


# ============================================================================
# CHAPTER 11: Slack & Discord Integrations (BONUS)
# ============================================================================

@app.post("/integrations", status_code=201)
async def register_integration(data: dict, db: Session = Depends(get_db)):
    """Register Slack or Discord integration"""
    integration_type = data.get("type")
    webhook_url = data.get("webhook_url")
    username = data.get("username", "ProxyWatch")
    events = data.get("events", ["alert.fired", "alert.resolved"])
    
    if not webhook_url or not integration_type:
        raise HTTPException(status_code=400, detail="webhook_url and type required")
    
    integration_id = f"int-{uuid.uuid4().hex[:8]}"
    
    integration = Integration(
        id=integration_id,
        type=integration_type,
        webhook_url=webhook_url,
        username=username,
        events=json.dumps(events)
    )
    db.add(integration)
    db.commit()
    
    return {
        "id": integration_id,
        "type": integration_type,
        "webhook_url": webhook_url
    }


# ============================================================================
# CHAPTER 12: Metrics
# ============================================================================

@app.get("/metrics")
async def get_metrics(db: Session = Depends(get_db)):
    """Get operational monitoring data"""
    total_checks = db.query(ProxyCheck).count()
    current_pool_size = db.query(Proxy).count()
    active_alerts = db.query(Alert).filter_by(status=AlertStatus.ACTIVE).count()
    total_alerts = db.query(Alert).count()
    webhook_deliveries = db.query(WebhookDelivery).count()
    
    return {
        "total_checks": total_checks,
        "current_pool_size": current_pool_size,
        "active_alerts": active_alerts,
        "total_alerts": total_alerts,
        "webhook_deliveries": webhook_deliveries
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
