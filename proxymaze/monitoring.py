"""Background monitoring service"""
import asyncio
import aiohttp
from datetime import datetime
from sqlalchemy.orm import Session
from models import Proxy, ProxyCheck, ProxyStatus, Alert, AlertStatus, Config
from database import SessionLocal
from typing import List
import json
import uuid
from alerts import AlertManager


class MonitoringService:
    def __init__(self):
        self.is_running = False
        self.alert_manager = AlertManager()
        
    async def check_proxy(self, proxy: Proxy, timeout_ms: int) -> bool:
        """Check if proxy is up"""
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(proxy.url) as resp:
                    return 200 <= resp.status < 300
        except (asyncio.TimeoutError, aiohttp.ClientError, Exception):
            return False
    
    async def run_checks(self, db: Session):
        """Run proxy health checks"""
        config = db.query(Config).filter_by(id="default").first()
        if not config:
            config = Config()
            db.add(config)
            db.commit()
        
        interval = config.check_interval_seconds
        timeout_ms = config.request_timeout_ms
        
        while self.is_running:
            proxies = db.query(Proxy).all()
            
            # Check all proxies concurrently
            tasks = [self.check_proxy(p, timeout_ms) for p in proxies]
            if tasks:
                results = await asyncio.gather(*tasks)
                
                # Update proxy status
                for proxy, is_up in zip(proxies, results):
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
                await self.alert_manager.evaluate_alerts(db)
            
            await asyncio.sleep(interval)
    
    async def start(self):
        """Start monitoring service"""
        if not self.is_running:
            self.is_running = True
            db = SessionLocal()
            try:
                await self.run_checks(db)
            finally:
                db.close()
    
    def stop(self):
        """Stop monitoring service"""
        self.is_running = False


# Global monitoring service instance
monitoring_service = MonitoringService()
