import asyncio
import httpx
from typing import Any
from . import state, utils, webhooks

def evaluate_alert_state() -> list[dict[str, Any]]:
    total = len(state.proxy_registry)
    failed_ids = sorted([pid for pid, rec in state.proxy_registry.items() if rec.get("status") == "down"])
    failed_count = len(failed_ids)
    failure_rate = (failed_count / total) if total else 0.0
    now = utils.timestamp_now()
    events: list[dict[str, Any]] = []

    active_alert = next((a for a in reversed(state.alert_records) if a.get("status") == "active"), None)
    breach = total > 0 and failure_rate >= state.BREACH_LEVEL

    if breach:
        if active_alert is None:
            state.alert_records.append({
                "alert_id": utils.create_alert_identifier(),
                "status": "active",
                "failure_rate": failure_rate,
                "total_proxies": total,
                "failed_proxies": failed_count,
                "failed_proxy_ids": failed_ids,
                "threshold": state.BREACH_LEVEL,
                "fired_at": now,
                "resolved_at": None,
                "message": "Proxy pool failure rate exceeded threshold",
            })
            current = state.alert_records[-1]
            events.append({
                "event": "alert.fired",
                "alert_id": current["alert_id"],
                "fired_at": current["fired_at"],
                "failure_rate": current["failure_rate"],
                "total_proxies": current["total_proxies"],
                "failed_proxies": current["failed_proxies"],
                "failed_proxy_ids": current["failed_proxy_ids"],
                "threshold": current["threshold"],
                "message": current["message"],
            })
            return events

        active_alert.update({
            "failure_rate": failure_rate,
            "total_proxies": total,
            "failed_proxies": failed_count,
            "failed_proxy_ids": failed_ids,
            "message": "Proxy pool failure rate exceeded threshold"
        })
        return events

    if active_alert is not None:
        active_alert["status"] = "resolved"
        active_alert["resolved_at"] = now
        events.append({
            "event": "alert.resolved",
            "alert_id": active_alert["alert_id"],
            "resolved_at": now,
        })
    return events

async def execute_health_check(client: httpx.AsyncClient, url: str, timeout_s: float) -> bool:
    timeout = httpx.Timeout(timeout_s)
    try:
        r = await client.head(url, timeout=timeout, follow_redirects=True)
        if r.status_code == 405:
            r = await client.get(url, timeout=timeout, follow_redirects=True)
        return 200 <= r.status_code < 300
    except httpx.RequestError:
        return False

async def background_monitoring_cycle() -> None:
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(limits=limits) as client:
        while True:
            with state.app_mutex:
                cfg = state.service_settings.copy()
                targets = [(pid, state.proxy_registry[pid]["url"]) for pid in sorted(state.proxy_registry.keys())]

            interval = cfg["check_interval_seconds"]
            timeout_s = cfg["request_timeout_ms"] / 1000.0

            if targets:
                results = await asyncio.gather(
                    *[execute_health_check(client, url, timeout_s) for _, url in targets],
                    return_exceptions=True,
                )
                at = utils.timestamp_now()
                with state.app_mutex:
                    for (pid, _), ok in zip(targets, results):
                        if pid not in state.proxy_registry: continue
                        is_up = bool(ok) if not isinstance(ok, Exception) else False
                        state.operational_stats["total_checks"] += 1
                        rec = state.proxy_registry[pid]
                        if is_up:
                            rec["status"] = "up"
                            rec["consecutive_failures"] = 0
                            rec["total_successes"] = int(rec.get("total_successes") or 0) + 1
                        else:
                            rec["consecutive_failures"] = int(rec.get("consecutive_failures") or 0) + 1
                            rec["status"] = "down"
                        rec["last_checked_at"] = at
                        rec["total_checks"] = int(rec.get("total_checks") or 0) + 1
                        rec.setdefault("history", []).append({"checked_at": at, "status": rec["status"]})

            with state.app_mutex:
                events = evaluate_alert_state()
            for event_payload in events:
                await webhooks.stage_outgoing_events(event_payload)

            wake = state.probe_trigger
            if wake is None: break
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=float(interval))
            except asyncio.TimeoutError:
                pass
