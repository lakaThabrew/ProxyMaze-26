"""Database models for ProxyMaze"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from enum import Enum
import uuid

Base = declarative_base()


class ProxyStatus(str, Enum):
    PENDING = "pending"
    UP = "up"
    DOWN = "down"


class AlertStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"


class Proxy(Base):
    __tablename__ = "proxies"
    
    id = Column(String, primary_key=True)
    url = Column(String, nullable=False, unique=True)
    status = Column(String, default=ProxyStatus.PENDING)
    last_checked_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, default=0)
    total_checks = Column(Integer, default=0)
    successful_checks = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def uptime_percentage(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return (self.successful_checks / self.total_checks) * 100


class ProxyCheck(Base):
    __tablename__ = "proxy_checks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    proxy_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    
    alert_id = Column(String, primary_key=True)
    status = Column(String, default=AlertStatus.ACTIVE)
    failure_rate = Column(Float, nullable=False)
    total_proxies = Column(Integer, nullable=False)
    failed_proxies = Column(Integer, nullable=False)
    failed_proxy_ids = Column(Text, nullable=False)  # JSON string
    threshold = Column(Float, default=0.20)
    fired_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Webhook(Base):
    __tablename__ = "webhooks"
    
    webhook_id = Column(String, primary_key=True)
    url = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    
class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    webhook_id = Column(String, nullable=False)
    alert_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)  # "alert.fired" or "alert.resolved"
    status = Column(String, default="pending")  # pending, delivered, failed
    payload = Column(Text, nullable=False)
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_attempted_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)


class Integration(Base):
    __tablename__ = "integrations"
    
    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)  # "slack" or "discord"
    webhook_url = Column(String, nullable=False)
    username = Column(String, nullable=False)
    events = Column(Text, nullable=False)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class Config(Base):
    __tablename__ = "config"
    
    id = Column(String, primary_key=True, default="default")
    check_interval_seconds = Column(Integer, default=15)
    request_timeout_ms = Column(Integer, default=3000)
    updated_at = Column(DateTime, default=datetime.utcnow)
