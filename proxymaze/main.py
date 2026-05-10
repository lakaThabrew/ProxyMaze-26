"""ProxyMaze — minimal FastAPI backend (in-memory state)."""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict, Field, field_validator
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

app_mutex = threading.Lock()
event_loop_ref: asyncio.AbstractEventLoop | None = None
probe_trigger: asyncio.Event | None = None

# --- In-memory state (guard reads/writes with app_mutex) ---

service_settings: dict[str, int] = {
    "check_interval_seconds": 15,
    "request_timeout_ms": 3000,
}

proxy_registry: dict[str, dict[str, Any]] = {}
alert_records: list[dict[str, Any]] = []
webhook_endpoints: dict[str, str] = {}
next_webhook_seq = 1
integration_configs: dict[str, dict[str, Any]] = {}
next_integration_seq = 1
BREACH_LEVEL = 0.2
dispatch_buffer: asyncio.Queue[dict[str, Any]] | None = None
dispatcher_process: asyncio.Task[None] | None = None
delivery_tracking_enqueued: set[tuple[str, str]] = set()
delivery_tracking_done: set[tuple[str, str]] = set()
operational_stats: dict[str, int] = {
    "total_checks": 0,
    "webhook_deliveries": 0,
}


def trigger_immediate_probe() -> None:
    loop = event_loop_ref
    ev = probe_trigger
    if loop is not None and ev is not None:
        loop.call_soon_threadsafe(ev.set)


def timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def create_alert_identifier() -> str:
    return f"alert-{uuid4().hex[:6]}"


def derive_event_signature(payload: dict[str, Any]) -> str:
    if payload["event"] == "alert.fired":
        return f"alert.fired:{payload['alert_id']}"
    return f"alert.resolved:{payload['alert_id']}"


def convert_iso_to_unix(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def fetch_alert_from_store(alert_id: str) -> dict[str, Any] | None:
    for alert in reversed(alert_records):
        if alert.get("alert_id") == alert_id:
            return alert
    return None


def prepare_external_payload(
    integration: dict[str, Any], event_payload: dict[str, Any]
) -> dict[str, Any]:
    """Return Slack Block Kit or Discord Embeds payload for an alert event."""
    event = event_payload["event"]
    alert_id = event_payload["alert_id"]
    username = integration.get("username") or "ProxyMaze"

    alert_data = fetch_alert_from_store(alert_id) or {}
    failure_rate = float(event_payload.get("failure_rate", alert_data.get("failure_rate", 0.0)))
    failed_proxies = int(event_payload.get("failed_proxies", alert_data.get("failed_proxies", 0)))
    total_proxies = int(event_payload.get("total_proxies", alert_data.get("total_proxies", 0)))
    threshold = float(event_payload.get("threshold", alert_data.get("threshold", BREACH_LEVEL)))
    failed_ids = list(event_payload.get("failed_proxy_ids", alert_data.get("failed_proxy_ids", [])) or [])
    fired_at = event_payload.get("fired_at", alert_data.get("fired_at"))
    resolved_at = event_payload.get("resolved_at", alert_data.get("resolved_at"))

    if integration.get("type") == "discord":
        color = 0xD7263D if event == "alert.fired" else 0x2ECC71
        title = "Proxy pool breach" if event == "alert.fired" else "Proxy pool recovered"
        desc = (
            f"Failure rate is {failure_rate:.2%} (threshold {threshold:.0%})."
            if event == "alert.fired"
            else f"Alert `{alert_id}` resolved."
        )
        return {
            "username": username,
            "embeds": [
                {
                    "title": title,
                    "description": desc,
                    "color": color,
                    "fields": [
                        {"name": "Alert ID", "value": str(alert_id), "inline": True},
                        {"name": "Failure rate", "value": f"{failure_rate:.2%}", "inline": True},
                        {
                            "name": "Failed Proxies",
                            "value": f"{failed_proxies}/{total_proxies}",
                            "inline": True,
                        },
                        {"name": "Threshold", "value": f"{threshold:.0%}", "inline": True},
                        {
                            "name": "Failed IDs",
                            "value": (", ".join(failed_ids) if failed_ids else "none"),
                            "inline": False,
                        },
                    ],
                    "footer": {"text": "ProxyMaze Alerts"},
                }
            ],
        }

    # Slack (grader spec): legacy payload with attachments.
    header_text = "Proxy pool breach" if event == "alert.fired" else "Proxy pool recovered"
    summary_text = (
        f"{header_text}: {failure_rate:.2%} failing ({failed_proxies}/{total_proxies})"
        if event == "alert.fired"
        else f"{header_text}: alert {alert_id} resolved"
    )
    ts_source = fired_at or resolved_at or timestamp_now()
    ts = convert_iso_to_unix(ts_source)
    color = "#D7263D" if event == "alert.fired" else "#2ECC71"
    failed_line = ", ".join(failed_ids) if failed_ids else "none"

    fields = [
        {"title": "Alert ID", "value": str(alert_id)},
        {"title": "Failure Rate", "value": f"{failure_rate:.2%}"},
        {"title": "Failed Proxies", "value": f"{failed_proxies}/{total_proxies}"},
        {"title": "Threshold", "value": f"{threshold:.0%}"},
        {"title": "Failed IDs", "value": failed_line},
        {"title": "Fired At", "value": str(fired_at or "n/a")},
    ]

    return {
        "username": username,
        "text": summary_text,
        "attachments": [
            {
                "color": color,
                "fields": fields,
                "footer": "ProxyMaze Alerts",
                "ts": ts,
            }
        ],
    }


def evaluate_alert_state() -> list[dict[str, Any]]:
    """Maintain one-active-alert lifecycle based on current proxy states."""
    total = len(proxy_registry)
    failed_ids = sorted([pid for pid, rec in proxy_registry.items() if rec.get("status") == "down"])
    failed_count = len(failed_ids)
    failure_rate = (failed_count / total) if total else 0.0
    now = timestamp_now()
    events: list[dict[str, Any]] = []

    active_alert = next((a for a in reversed(alert_records) if a.get("status") == "active"), None)
    breach = total > 0 and failure_rate >= BREACH_LEVEL

    if breach:
        if active_alert is None:
            alert_records.append(
                {
                    "alert_id": create_alert_identifier(),
                    "status": "active",
                    "failure_rate": failure_rate,
                    "total_proxies": total,
                    "failed_proxies": failed_count,
                    "failed_proxy_ids": failed_ids,
                    "threshold": BREACH_LEVEL,
                    "fired_at": now,
                    "resolved_at": None,
                    "message": "Proxy pool failure rate exceeded threshold",
                }
            )
            current = alert_records[-1]
            events.append(
                {
                    "event": "alert.fired",
                    "alert_id": current["alert_id"],
                    "fired_at": current["fired_at"],
                    "failure_rate": current["failure_rate"],
                    "total_proxies": current["total_proxies"],
                    "failed_proxies": current["failed_proxies"],
                    "failed_proxy_ids": current["failed_proxy_ids"],
                    "threshold": current["threshold"],
                    "message": current["message"],
                }
            )
            return events

        # Keep the active alert consistent with current pool state.
        active_alert["failure_rate"] = failure_rate
        active_alert["total_proxies"] = total
        active_alert["failed_proxies"] = failed_count
        active_alert["failed_proxy_ids"] = failed_ids
        active_alert["threshold"] = BREACH_LEVEL
        active_alert["message"] = "Proxy pool failure rate exceeded threshold"
        return events

    if active_alert is not None:
        active_alert["status"] = "resolved"
        active_alert["resolved_at"] = now
        events.append(
            {
                "event": "alert.resolved",
                "alert_id": active_alert["alert_id"],
                "resolved_at": now,
            }
        )
    return events


async def stage_outgoing_events(event_payload: dict[str, Any]) -> None:
    queue = dispatch_buffer
    if queue is None:
        return
    event_key = derive_event_signature(event_payload)
    with app_mutex:
        webhooks = list(webhook_endpoints.items())
        integrations = list(integration_configs.items())
        to_enqueue: list[dict[str, Any]] = []
        for webhook_id, url in webhooks:
            recipient_id = f"webhook:{webhook_id}"
            marker = (event_key, recipient_id)
            if marker in delivery_tracking_done or marker in delivery_tracking_enqueued:
                continue
            delivery_tracking_enqueued.add(marker)
            to_enqueue.append(
                {
                    "recipient_id": recipient_id,
                    "url": url,
                    "event_key": event_key,
                    "payload": dict(event_payload),
                }
            )

        for integration_id, integration in integrations:
            if event_payload["event"] not in integration.get("events", ["alert.fired", "alert.resolved"]):
                continue
            recipient_id = f"integration:{integration_id}"
            marker = (event_key, recipient_id)
            if marker in delivery_tracking_done or marker in delivery_tracking_enqueued:
                continue
            delivery_tracking_enqueued.add(marker)
            to_enqueue.append(
                {
                    "recipient_id": recipient_id,
                    "url": integration["webhook_url"],
                    "event_key": event_key,
                    "payload": prepare_external_payload(integration, dict(event_payload)),
                }
            )
    for item in to_enqueue:
        await queue.put(item)


async def event_dispatcher_loop() -> None:
    queue = dispatch_buffer
    if queue is None:
        return
    timeout = httpx.Timeout(8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        while True:
            item = await queue.get()
            recipient_id = item["recipient_id"]
            url = item["url"]
            event_key = item["event_key"]
            payload = item["payload"]
            marker = (event_key, recipient_id)
            backoff_s = 1.0
            try:
                while True:
                    try:
                        # Preserve POST across redirects (some capture servers front with redirects).
                        target = url
                        redirects = 0
                        while True:
                            resp = await client.post(
                                target,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                            )
                            if (
                                resp.status_code in (301, 302, 303, 307, 308)
                                and "location" in resp.headers
                                and redirects < 5
                            ):
                                loc = resp.headers["location"]
                                if loc.startswith("/"):
                                    p = httpx.URL(target)
                                    loc = str(p.copy_with(path=loc, query=None, fragment=None))
                                target = loc
                                redirects += 1
                                continue
                            break
                        if 200 <= resp.status_code < 300:
                            with app_mutex:
                                delivery_tracking_enqueued.discard(marker)
                                delivery_tracking_done.add(marker)
                                operational_stats["webhook_deliveries"] += 1
                            break
                        if resp.status_code in (500, 502, 503, 504):
                            await asyncio.sleep(backoff_s)
                            backoff_s = min(backoff_s * 2.0, 30.0)
                            continue
                        with app_mutex:
                            delivery_tracking_enqueued.discard(marker)
                            # Do not keep re-enqueuing forever on permanent 4xx responses.
                            delivery_tracking_done.add(marker)
                        break
                    except httpx.RequestError:
                        await asyncio.sleep(backoff_s)
                        backoff_s = min(backoff_s * 2.0, 30.0)
            finally:
                queue.task_done()


async def execute_health_check(client: httpx.AsyncClient, url: str, timeout_s: float) -> bool:
    timeout = httpx.Timeout(timeout_s)
    try:
        r = await client.head(url, timeout=timeout, follow_redirects=True)
        if r.status_code == 405:
            r = await client.get(url, timeout=timeout, follow_redirects=True)
        return 200 <= r.status_code < 300
    except httpx.RequestError:
        # Timeout / connection failures / refusal are down by definition.
        return False


async def background_monitoring_cycle() -> None:
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(limits=limits) as client:
        while True:
            with app_mutex:
                cfg = service_settings.copy()
                targets = [(pid, proxy_registry[pid]["url"]) for pid in sorted(proxy_registry.keys())]

            interval = cfg["check_interval_seconds"]
            timeout_s = cfg["request_timeout_ms"] / 1000.0

            if targets:
                # Probe in parallel so a round isn't N * timeout.
                results = await asyncio.gather(
                    *[execute_health_check(client, url, timeout_s) for _, url in targets],
                    return_exceptions=True,
                )
                at = timestamp_now()
                with app_mutex:
                    for (pid, _), ok in zip(targets, results):
                        if pid not in proxy_registry:
                            continue
                        is_up = bool(ok) if not isinstance(ok, Exception) else False
                        operational_stats["total_checks"] += 1
                        rec = proxy_registry[pid]
                        if is_up:
                            rec["status"] = "up"
                            rec["consecutive_failures"] = 0
                        else:
                            rec["consecutive_failures"] = int(rec.get("consecutive_failures") or 0) + 1
                            rec["status"] = "down"
                        rec["last_checked_at"] = at
                        rec["total_checks"] = int(rec.get("total_checks") or 0) + 1
                        if is_up:
                            rec["total_successes"] = int(rec.get("total_successes") or 0) + 1
                        history = rec.setdefault("history", [])
                        history.append({"checked_at": at, "status": rec["status"]})

            with app_mutex:
                events = evaluate_alert_state()
            for event_payload in events:
                await stage_outgoing_events(event_payload)

            wake = probe_trigger
            if wake is None:
                break
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=float(interval))
            except asyncio.TimeoutError:
                pass


@asynccontextmanager
async def app_lifecycle_manager(app: FastAPI):
    global event_loop_ref, probe_trigger, dispatch_buffer, dispatcher_process
    event_loop_ref = asyncio.get_running_loop()
    probe_trigger = asyncio.Event()
    dispatch_buffer = asyncio.Queue()
    dispatcher_process = asyncio.create_task(event_dispatcher_loop())
    task = asyncio.create_task(background_monitoring_cycle())
    try:
        yield
    finally:
        task.cancel()
        if dispatcher_process is not None:
            dispatcher_process.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if dispatcher_process is not None:
            try:
                await dispatcher_process
            except asyncio.CancelledError:
                pass
        dispatcher_process = None
        dispatch_buffer = None
        event_loop_ref = None
        probe_trigger = None


app = FastAPI(title="ProxyMaze", lifespan=app_lifecycle_manager)

# Trust X-Forwarded-* from Render so OpenAPI / logs see https and the public host.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
# Browser clients (Swagger "Try it out", local SPAs) may not be same-origin in some tools.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
    )
    # Relative base so Swagger UI builds https://<host>/... instead of a bad/missing URL.
    openapi_schema["servers"] = [{"url": "/", "description": "This deployment"}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


# --- Pydantic models ---


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


# --- Helpers ---


def extract_id_from_proxy_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("proxy URL must be an absolute http(s) URL with a host")
    path = (parsed.path or "").rstrip("/")
    if path:
        segment = path.split("/")[-1]
    else:
        segment = ""
    if not segment:
        raise ValueError(
            "proxy URL must have a non-empty last path segment used as id (e.g. .../px-101)"
        )
    return segment


def consolidate_settings(data: dict[str, int], update: UpdateSettings) -> dict[str, int]:
    out = data.copy()
    if update.check_interval_seconds is not None:
        out["check_interval_seconds"] = update.check_interval_seconds
    if update.request_timeout_ms is not None:
        out["request_timeout_ms"] = update.request_timeout_ms
    return out


def format_proxy_detailed_view(rec: dict[str, Any]) -> DetailedProxyInfo:
    total_checks = int(rec.get("total_checks") or 0)
    total_successes = int(rec.get("total_successes") or 0)
    uptime_percentage = round((total_successes / total_checks) * 100.0, 1) if total_checks else 0.0
    history = [CheckEvent(**h) for h in rec.get("history", [])]
    return DetailedProxyInfo(
        id=rec["id"],
        url=rec["url"],
        status=rec["status"],
        last_checked_at=rec.get("last_checked_at"),
        consecutive_failures=int(rec.get("consecutive_failures") or 0),
        total_checks=total_checks,
        uptime_percentage=uptime_percentage,
        history=history,
    )


# --- Routes ---


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "ProxyMaze API", "health": "/health", "docs": "/docs"}


@app.get("/health", response_model=ServiceStatus)
def health() -> ServiceStatus:
    return ServiceStatus()


@app.post("/config", response_model=CurrentSettings)
def post_config(body: UpdateSettings) -> CurrentSettings:
    """Set monitoring cadence (`check_interval_seconds`) and probe timeout (`request_timeout_ms`).

    Values take effect immediately: the next probe cycle uses the new timeout, and the sleep
    between full passes is interrupted so a new pass can start right away.
    """
    global service_settings
    with app_mutex:
        service_settings = consolidate_settings(service_settings, body)
        out = CurrentSettings(**service_settings)
    trigger_immediate_probe()
    return out


@app.get("/config", response_model=CurrentSettings)
def get_config() -> CurrentSettings:
    with app_mutex:
        return CurrentSettings(**service_settings)


@app.post(
    "/proxies",
    response_model=BulkLoadResult,
    status_code=status.HTTP_201_CREATED,
)
def post_proxies(body: BulkProxyLoad) -> BulkLoadResult:
    global proxy_registry
    with app_mutex:
        if body.replace:
            proxy_registry = {}

        accepted = 0
        accepted_ids: list[str] = []
        errors: list[str] = []

        for raw in body.proxies:
            url = raw.strip()
            try:
                pid = extract_id_from_proxy_url(url)
            except ValueError as e:
                errors.append(f"{raw!r}: {e}")
                continue

            proxy_registry[pid] = {
                "id": pid,
                "url": url,
                "status": "pending",
                "last_checked_at": None,
                "consecutive_failures": 0,
                "total_checks": 0,
                "total_successes": 0,
                "history": [],
            }
            accepted += 1
            accepted_ids.append(pid)

        if errors and accepted == 0 and body.proxies:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "No valid proxies in request", "errors": errors},
            )

        records = [ProxyInfo(**proxy_registry[k]) for k in sorted(accepted_ids)]
        result = BulkLoadResult(accepted=accepted, proxies=records)
    trigger_immediate_probe()
    return result


@app.get("/proxies", response_model=ProxyRegistryOverview)
def get_proxies() -> ProxyRegistryOverview:
    with app_mutex:
        items = [ProxyInfo(**proxy_registry[k]) for k in sorted(proxy_registry.keys())]
        total = len(items)
        up = sum(1 for p in items if p.status == "up")
        down = sum(1 for p in items if p.status == "down")
        failure_rate = (down / total) if total else 0.0
        return ProxyRegistryOverview(
            total=total,
            up=up,
            down=down,
            failure_rate=failure_rate,
            proxies=items,
        )


@app.get("/proxies/{proxy_id}", response_model=DetailedProxyInfo)
def get_proxy_by_id(proxy_id: str) -> DetailedProxyInfo:
    with app_mutex:
        rec = proxy_registry.get(proxy_id)
        if rec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": f"Proxy '{proxy_id}' not found"},
            )
        return format_proxy_detailed_view(dict(rec))


@app.get("/proxies/{proxy_id}/history", response_model=list[CheckEvent])
def get_proxy_history(proxy_id: str) -> list[CheckEvent]:
    with app_mutex:
        rec = proxy_registry.get(proxy_id)
        if rec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": f"Proxy '{proxy_id}' not found"},
            )
        return [CheckEvent(**h) for h in rec.get("history", [])]


@app.delete("/proxies", status_code=status.HTTP_204_NO_CONTENT)
def delete_proxies() -> Response:
    global proxy_registry
    with app_mutex:
        proxy_registry = {}
    trigger_immediate_probe()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/alerts", response_model=list[AlertDetail])
def get_alerts() -> list[AlertDetail]:
    with app_mutex:
        # Alert history survives proxy pool purge.
        return [AlertDetail(**dict(a)) for a in alert_records]


@app.post(
    "/webhooks",
    response_model=WebhookRegistration,
    status_code=status.HTTP_201_CREATED,
)
def post_webhooks(body: RegisterWebhook) -> WebhookRegistration:
    global next_webhook_seq
    with app_mutex:
        webhook_id = f"wh-{next_webhook_seq}"
        next_webhook_seq += 1
        webhook_endpoints[webhook_id] = body.url
        return WebhookRegistration(webhook_id=webhook_id, url=body.url)


@app.post(
    "/integrations",
    response_model=IntegrationAdded,
    status_code=status.HTTP_201_CREATED,
)
def post_integrations(body: AddIntegration) -> IntegrationAdded:
    global next_integration_seq
    with app_mutex:
        integration_id = f"int-{next_integration_seq}"
        next_integration_seq += 1
        integration_configs[integration_id] = {
            "type": body.type,
            "webhook_url": body.webhook_url,
            "username": body.username,
            "events": list(body.events),
        }
        return IntegrationAdded(
            integration_id=integration_id,
            type=body.type,
            webhook_url=body.webhook_url,
            username=body.username,
            events=list(body.events),
        )


@app.get("/metrics", response_model=SystemMetrics)
def get_metrics() -> SystemMetrics:
    with app_mutex:
        active_alerts = sum(1 for a in alert_records if a.get("status") == "active")
        return SystemMetrics(
            total_checks=operational_stats["total_checks"],
            current_pool_size=len(proxy_registry),
            active_alerts=active_alerts,
            total_alerts=len(alert_records),
            webhook_deliveries=operational_stats["webhook_deliveries"],
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
