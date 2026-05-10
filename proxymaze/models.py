from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from urllib.parse import urlparse

class ServiceStatus(BaseModel):
    status: Literal["ok"] = "ok"

class UpdateSettings(BaseModel):
    check_interval_seconds: int | None = None
    request_timeout_ms: int | None = None

    @field_validator("check_interval_seconds")
    @classmethod
    def check_interval_valid(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("check_interval_seconds must be >= 1")
        return v

    @field_validator("request_timeout_ms")
    @classmethod
    def request_timeout_valid(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("request_timeout_ms must be >= 1")
        return v

class CurrentSettings(BaseModel):
    check_interval_seconds: int
    request_timeout_ms: int

class BulkProxyLoad(BaseModel):
    model_config = ConfigDict(extra="ignore")
    proxies: list[str] = Field(default_factory=list)
    replace: bool = False

    @field_validator("proxies")
    @classmethod
    def non_empty_strings(cls, v: list[str]) -> list[str]:
        for i, item in enumerate(v):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"proxies[{i}] must be a non-empty string")
        return v

class ProxyInfo(BaseModel):
    id: str
    url: str
    status: Literal["pending", "up", "down"] = "pending"
    last_checked_at: str | None = None
    consecutive_failures: int = 0

class BulkLoadResult(BaseModel):
    accepted: int
    proxies: list[ProxyInfo]

class ProxyRegistryOverview(BaseModel):
    total: int
    up: int
    down: int
    failure_rate: float
    proxies: list[ProxyInfo]

class CheckEvent(BaseModel):
    checked_at: str
    status: Literal["up", "down"]

class AlertDetail(BaseModel):
    alert_id: str
    status: Literal["active", "resolved"]
    failure_rate: float
    total_proxies: int
    failed_proxies: int
    failed_proxy_ids: list[str]
    threshold: float
    fired_at: str
    resolved_at: str | None
    message: str

class RegisterWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        value = v.strip()
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        return value

class WebhookRegistration(BaseModel):
    webhook_id: str
    url: str

class AddIntegration(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["slack", "discord"]
    webhook_url: str
    username: str = "ProxyMaze"
    events: list[Literal["alert.fired", "alert.resolved"]] = Field(
        default_factory=lambda: ["alert.fired", "alert.resolved"]
    )

    @field_validator("webhook_url")
    @classmethod
    def webhook_url_must_be_http(cls, v: str) -> str:
        value = v.strip()
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("webhook_url must be an absolute http(s) URL")
        return value

    @field_validator("username")
    @classmethod
    def username_non_empty(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("username must be non-empty")
        return value

    @field_validator("events")
    @classmethod
    def events_non_empty(
        cls, v: list[Literal["alert.fired", "alert.resolved"]]
    ) -> list[Literal["alert.fired", "alert.resolved"]]:
        if not v:
            raise ValueError("events must include at least one event")
        return v

class IntegrationAdded(BaseModel):
    integration_id: str
    type: Literal["slack", "discord"]
    webhook_url: str
    username: str
    events: list[Literal["alert.fired", "alert.resolved"]]

class SystemMetrics(BaseModel):
    total_checks: int
    current_pool_size: int
    active_alerts: int
    total_alerts: int
    webhook_deliveries: int

class DetailedProxyInfo(BaseModel):
    id: str
    url: str
    status: Literal["pending", "up", "down"]
    last_checked_at: str | None
    consecutive_failures: int
    total_checks: int
    uptime_percentage: float
    history: list[CheckEvent]
