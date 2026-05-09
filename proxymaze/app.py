"""ProxyMaze - Real-time proxy monitoring service"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from datetime import datetime
from .models import (
    Proxy, ProxyStatus, Alert, AlertStatus, Webhook, Config, 
    Integration, ProxyCheck, WebhookDelivery
)
from .database import init_db, get_db, SessionLocal
import json
import uuid
import asyncio
import aiohttp
import logging
import os

logger = logging.getLogger(__name__)


app = FastAPI(title="ProxyMaze", version="1.0.0")

THRESHOLD = 0.20
monitoring_task = None
webhook_task = None


@app.get("/")
async def root():
    return {"message": "ProxyMaze API", "health": "/health", "docs": "/docs"}


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# Background monitoring
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
        if not active_alert:
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
            
            # Queue webhooks
            integrations = db.query(Integration).all()
            for integration in integrations:
                events = json.loads(integration.events)
                if "alert.fired" in events:
                    payload = {
                        "event": "alert.fired",
                        "alert_id": alert_id,
                        "fired_at": alert.fired_at.isoformat() + "Z",
                        "failure_rate": failure_rate,
                        "total_proxies": total,
                        "failed_proxies": failed,
                        "failed_proxy_ids": failed_proxy_ids,
                        "threshold": THRESHOLD,
                        "message": "Proxy pool failure rate exceeded threshold"
                    }
                    delivery = WebhookDelivery(
                        webhook_id=integration.id,
                        alert_id=alert_id,
                        event_type="alert.fired",
                        status="pending",
                        payload=json.dumps(payload)
                    )
                    db.add(delivery)
            db.commit()
        else:
            active_alert.failure_rate = failure_rate
            active_alert.failed_proxies = failed
            active_alert.failed_proxy_ids = json.dumps(failed_proxy_ids)
            db.commit()
    else:
        if active_alert:
            active_alert.status = AlertStatus.RESOLVED
            active_alert.resolved_at = datetime.utcnow()
            db.commit()
            
            # Queue resolved webhooks
            integrations = db.query(Integration).all()
            for integration in integrations:
                events = json.loads(integration.events)
                if "alert.resolved" in events:
                    payload = {
                        "event": "alert.resolved",
                        "alert_id": active_alert.alert_id,
                        "resolved_at": active_alert.resolved_at.isoformat() + "Z"
                    }
                    delivery = WebhookDelivery(
                        webhook_id=integration.id,
                        alert_id=active_alert.alert_id,
                        event_type="alert.resolved",
                        status="pending",
                        payload=json.dumps(payload)
                    )
                    db.add(delivery)
            db.commit()


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
            
            tasks = [check_proxy_health(p.url, timeout_ms / 1000.0) for p in proxies]
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for proxy, result in zip(proxies, results):
                    is_up = isinstance(result, bool) and result
                    new_status = ProxyStatus.UP if is_up else ProxyStatus.DOWN
                    
                    if new_status == ProxyStatus.DOWN:
                        proxy.consecutive_failures += 1
                    else:
                        proxy.consecutive_failures = 0
                    
                    proxy.total_checks += 1
                    if is_up:
                        proxy.successful_checks += 1
                    proxy.status = new_status
                    proxy.last_checked_at = datetime.utcnow()
                    
                    check = ProxyCheck(
                        proxy_id=proxy.id,
                        status=new_status,
                        checked_at=datetime.utcnow()
                    )
                    db.add(check)
                
                db.commit()
                await evaluate_alerts(db)
            
            await asyncio.sleep(interval)
        except Exception as e:
            print(f"Monitoring error: {e}")
            await asyncio.sleep(5)
        finally:
            db.close()


async def process_webhook_deliveries():
    """Process pending webhook deliveries"""
    while True:
        db = SessionLocal()
        try:
            pending = db.query(WebhookDelivery).filter_by(status="pending").all()
            for delivery in pending:
                webhook = db.query(Webhook).filter_by(id=delivery.webhook_id).first()
                if not webhook:
                    delivery.status = "failed"
                    db.commit()
                    continue
                
                try:
                    timeout = aiohttp.ClientTimeout(total=60)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(
                            webhook.url,
                            data=delivery.payload,
                            headers={"Content-Type": "application/json"}
                        ) as resp:
                            if 200 <= resp.status < 300:
                                delivery.status = "delivered"
                                delivery.delivered_at = datetime.utcnow()
                            elif resp.status in [500, 502, 503, 504]:
                                delivery.attempts += 1
                                delivery.last_attempted_at = datetime.utcnow()
                                if delivery.attempts >= 5:
                                    delivery.status = "failed"
                            else:
                                delivery.status = "failed"
                except Exception:
                    delivery.attempts += 1
                    delivery.last_attempted_at = datetime.utcnow()
                    if delivery.attempts >= 5:
                        delivery.status = "failed"
                
                db.commit()
            
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Webhook error: {e}")
            await asyncio.sleep(5)
        finally:
            db.close()


@app.on_event("startup")
async def startup():
    """Initialize and start background tasks"""
    global monitoring_task, webhook_task
    try:
        db_url = os.getenv("DATABASE_URL", "sqlite:///./proxymaze.db")
        logger.info(f"Using database: {db_url[:50]}..." if len(db_url) > 50 else db_url)
        init_db()
        logger.info("Database initialized successfully")
        
        monitoring_task = asyncio.create_task(run_proxy_monitoring())
        logger.info("Proxy monitoring task started")
        
        webhook_task = asyncio.create_task(process_webhook_deliveries())
        logger.info("Webhook delivery task started")
    except Exception as e:
        logger.error(f"Startup error: {str(e)}", exc_info=True)
        raise



@app.on_event("shutdown")
async def shutdown():
    """Clean up"""
    global monitoring_task, webhook_task
    if monitoring_task:
        monitoring_task.cancel()
    if webhook_task:
        webhook_task.cancel()


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/config")
async def set_config(config_data: dict, db: Session = Depends(get_db)):
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
    config = db.query(Config).filter_by(id="default").first()
    if not config:
        config = Config(id="default")
        db.add(config)
        db.commit()
    
    return {
        "check_interval_seconds": config.check_interval_seconds,
        "request_timeout_ms": config.request_timeout_ms
    }


def extract_proxy_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


@app.post("/proxies", status_code=201)
async def add_proxies(data: dict, db: Session = Depends(get_db)):
    proxies_list = data.get("proxies", [])
    replace = data.get("replace", False)
    
    if replace:
        db.query(Proxy).delete()
        db.commit()
    
    accepted = 0
    created_proxies = []
    
    for url in proxies_list:
        proxy_id = extract_proxy_id(url)
        existing = db.query(Proxy).filter_by(id=proxy_id).first()
        
        if not existing:
            proxy = Proxy(id=proxy_id, url=url, status=ProxyStatus.PENDING)
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
    return {"accepted": accepted, "proxies": created_proxies}


@app.get("/proxies")
async def get_proxies(db: Session = Depends(get_db)):
    proxies = db.query(Proxy).all()
    total = len(proxies)
    up = sum(1 for p in proxies if p.status == ProxyStatus.UP)
    down = sum(1 for p in proxies if p.status == ProxyStatus.DOWN)
    failure_rate = down / total if total > 0 else 0.0
    
    proxies_data = [{
        "id": p.id,
        "url": p.url,
        "status": p.status,
        "last_checked_at": p.last_checked_at.isoformat() + "Z" if p.last_checked_at else None,
        "consecutive_failures": p.consecutive_failures
    } for p in proxies]
    
    return {
        "total": total,
        "up": up,
        "down": down,
        "failure_rate": failure_rate,
        "proxies": proxies_data
    }


@app.get("/proxies/{proxy_id}")
async def get_proxy(proxy_id: str, db: Session = Depends(get_db)):
    proxy = db.query(Proxy).filter_by(id=proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    history = db.query(ProxyCheck).filter_by(proxy_id=proxy_id).all()
    history_data = [{
        "checked_at": h.checked_at.isoformat() + "Z",
        "status": h.status
    } for h in history]
    
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


@app.get("/proxies/{proxy_id}/history")
async def get_proxy_history(proxy_id: str, db: Session = Depends(get_db)):
    proxy = db.query(Proxy).filter_by(id=proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    history = db.query(ProxyCheck).filter_by(proxy_id=proxy_id).all()
    return [{
        "checked_at": h.checked_at.isoformat() + "Z",
        "status": h.status
    } for h in history]


@app.delete("/proxies", status_code=204)
async def delete_proxies(db: Session = Depends(get_db)):
    db.query(Proxy).delete()
    db.commit()
    return Response(status_code=204)


@app.get("/alerts")
async def get_alerts(db: Session = Depends(get_db)):
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


@app.post("/webhooks", status_code=201)
async def register_webhook(data: dict, db: Session = Depends(get_db)):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    existing_webhook = db.query(Webhook).filter_by(url=url).first()
    if existing_webhook:
        return {"webhook_id": existing_webhook.webhook_id, "url": existing_webhook.url}

    webhook_id = f"wh-{uuid.uuid4().hex[:8]}"
    webhook = Webhook(webhook_id=webhook_id, url=url)
    db.add(webhook)
    db.commit()
    
    return {"webhook_id": webhook_id, "url": url}


@app.post("/integrations", status_code=201)
async def register_integration(data: dict, db: Session = Depends(get_db)):
    integration_type = data.get("type")
    webhook_url = data.get("webhook_url")
    username = data.get("username", "ProxyWatch")
    events = data.get("events", ["alert.fired", "alert.resolved"])
    
    if not webhook_url or not integration_type:
        raise HTTPException(status_code=400, detail="webhook_url and type required")

    existing_integration = db.query(Integration).filter_by(
        type=integration_type,
        webhook_url=webhook_url,
        username=username,
    ).first()
    if existing_integration:
        return {
            "id": existing_integration.id,
            "type": existing_integration.type,
            "webhook_url": existing_integration.webhook_url,
        }
    
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


@app.get("/metrics")
async def get_metrics(db: Session = Depends(get_db)):
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
