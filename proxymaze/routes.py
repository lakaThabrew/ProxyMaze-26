from fastapi import APIRouter, HTTPException, Response, status
from typing import Any
from . import state, models, utils

router = APIRouter()

def consolidate_settings(data: dict[str, int], update: models.UpdateSettings) -> dict[str, int]:
    out = data.copy()
    if update.check_interval_seconds is not None:
        out["check_interval_seconds"] = update.check_interval_seconds
    if update.request_timeout_ms is not None:
        out["request_timeout_ms"] = update.request_timeout_ms
    return out

def format_proxy_detailed_view(rec: dict[str, Any]) -> models.DetailedProxyInfo:
    total_checks = int(rec.get("total_checks") or 0)
    total_successes = int(rec.get("total_successes") or 0)
    uptime_percentage = round((total_successes / total_checks) * 100.0, 1) if total_checks else 0.0
    history = [models.CheckEvent(**h) for h in rec.get("history", [])]
    return models.DetailedProxyInfo(
        id=rec["id"], url=rec["url"], status=rec["status"],
        last_checked_at=rec.get("last_checked_at"),
        consecutive_failures=int(rec.get("consecutive_failures") or 0),
        total_checks=total_checks, uptime_percentage=uptime_percentage,
        history=history
    )

@router.get("/")
def root():
    return {"message": "ProxyMaze API", "health": "/health", "docs": "/docs"}

@router.get("/health", response_model=models.ServiceStatus)
def health():
    return models.ServiceStatus()

@router.post("/config", response_model=models.CurrentSettings)
def post_config(body: models.UpdateSettings):
    with state.app_mutex:
        state.service_settings = consolidate_settings(state.service_settings, body)
        out = models.CurrentSettings(**state.service_settings)
    utils.trigger_immediate_probe()
    return out

@router.get("/config", response_model=models.CurrentSettings)
def get_config():
    with state.app_mutex:
        return models.CurrentSettings(**state.service_settings)

@router.post("/proxies", response_model=models.BulkLoadResult, status_code=status.HTTP_201_CREATED)
def post_proxies(body: models.BulkProxyLoad):
    with state.app_mutex:
        if body.replace: state.proxy_registry = {}
        accepted = 0
        accepted_ids = []
        errors = []
        for raw in body.proxies:
            url = raw.strip()
            try:
                pid = utils.extract_id_from_proxy_url(url)
            except ValueError as e:
                errors.append(f"{raw!r}: {e}")
                continue
            state.proxy_registry[pid] = {
                "id": pid, "url": url, "status": "pending",
                "last_checked_at": None, "consecutive_failures": 0,
                "total_checks": 0, "total_successes": 0, "history": []
            }
            accepted += 1
            accepted_ids.append(pid)
        if errors and accepted == 0 and body.proxies:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "No valid proxies", "errors": errors})
        records = [models.ProxyInfo(**state.proxy_registry[k]) for k in sorted(accepted_ids)]
        result = models.BulkLoadResult(accepted=accepted, proxies=records)
    utils.trigger_immediate_probe()
    return result

@router.get("/proxies", response_model=models.ProxyRegistryOverview)
def get_proxies():
    with state.app_mutex:
        items = [models.ProxyInfo(**state.proxy_registry[k]) for k in sorted(state.proxy_registry.keys())]
        total = len(items)
        up = sum(1 for p in items if p.status == "up")
        down = sum(1 for p in items if p.status == "down")
        failure_rate = (down / total) if total else 0.0
        return models.ProxyRegistryOverview(total=total, up=up, down=down, failure_rate=failure_rate, proxies=items)

@router.get("/proxies/{proxy_id}", response_model=models.DetailedProxyInfo)
def get_proxy_by_id(proxy_id: str):
    with state.app_mutex:
        rec = state.proxy_registry.get(proxy_id)
        if rec is None: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": f"Proxy '{proxy_id}' not found"})
        return format_proxy_detailed_view(dict(rec))

@router.delete("/proxies", status_code=status.HTTP_204_NO_CONTENT)
def delete_proxies():
    with state.app_mutex: state.proxy_registry = {}
    utils.trigger_immediate_probe()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/alerts", response_model=list[models.AlertDetail])
def get_alerts():
    with state.app_mutex: return [models.AlertDetail(**dict(a)) for a in state.alert_records]

@router.post("/webhooks", response_model=models.WebhookRegistration, status_code=status.HTTP_201_CREATED)
def post_webhooks(body: models.RegisterWebhook):
    with state.app_mutex:
        webhook_id = f"wh-{state.next_webhook_seq}"
        state.next_webhook_seq += 1
        state.webhook_endpoints[webhook_id] = body.url
        return models.WebhookRegistration(webhook_id=webhook_id, url=body.url)

@router.post("/integrations", response_model=models.IntegrationAdded, status_code=status.HTTP_201_CREATED)
def post_integrations(body: models.AddIntegration):
    with state.app_mutex:
        integration_id = f"int-{state.next_integration_seq}"
        state.next_integration_seq += 1
        state.integration_configs[integration_id] = {
            "type": body.type, "webhook_url": body.webhook_url,
            "username": body.username, "events": list(body.events)
        }
        return models.IntegrationAdded(integration_id=integration_id, **state.integration_configs[integration_id])

@router.get("/metrics", response_model=models.SystemMetrics)
def get_metrics():
    with state.app_mutex:
        active_alerts = sum(1 for a in state.alert_records if a.get("status") == "active")
        return models.SystemMetrics(
            total_checks=state.operational_stats["total_checks"],
            current_pool_size=len(state.proxy_registry),
            active_alerts=active_alerts, total_alerts=len(state.alert_records),
            webhook_deliveries=state.operational_stats["webhook_deliveries"]
        )
