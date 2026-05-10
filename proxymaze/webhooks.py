import asyncio
import httpx
from typing import Any
from . import state, utils

def prepare_external_payload(
    integration: dict[str, Any], event_payload: dict[str, Any]
) -> dict[str, Any]:
    event = event_payload["event"]
    alert_id = event_payload["alert_id"]
    username = integration.get("username") or "ProxyMaze"

    alert_data = utils.fetch_alert_from_store(alert_id) or {}
    failure_rate = float(event_payload.get("failure_rate", alert_data.get("failure_rate", 0.0)))
    failed_proxies = int(event_payload.get("failed_proxies", alert_data.get("failed_proxies", 0)))
    total_proxies = int(event_payload.get("total_proxies", alert_data.get("total_proxies", 0)))
    threshold = float(event_payload.get("threshold", alert_data.get("threshold", state.BREACH_LEVEL)))
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
                        {"name": "Failed Proxies", "value": f"{failed_proxies}/{total_proxies}", "inline": True},
                        {"name": "Threshold", "value": f"{threshold:.0%}", "inline": True},
                        {"name": "Failed IDs", "value": (", ".join(failed_ids) if failed_ids else "none"), "inline": False},
                    ],
                    "footer": {"text": "ProxyMaze Alerts"},
                }
            ],
        }

    # Slack
    header_text = "Proxy pool breach" if event == "alert.fired" else "Proxy pool recovered"
    summary_text = (
        f"{header_text}: {failure_rate:.2%} failing ({failed_proxies}/{total_proxies})"
        if event == "alert.fired"
        else f"{header_text}: alert {alert_id} resolved"
    )
    ts_source = fired_at or resolved_at or utils.timestamp_now()
    ts = utils.convert_iso_to_unix(ts_source)
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
        "attachments": [{"color": color, "fields": fields, "footer": "ProxyMaze Alerts", "ts": ts}],
    }

async def stage_outgoing_events(event_payload: dict[str, Any]) -> None:
    queue = state.dispatch_buffer
    if queue is None:
        return
    event_key = utils.derive_event_signature(event_payload)
    with state.app_mutex:
        webhooks = list(state.webhook_endpoints.items())
        integrations = list(state.integration_configs.items())
        to_enqueue: list[dict[str, Any]] = []
        
        for webhook_id, url in webhooks:
            recipient_id = f"webhook:{webhook_id}"
            marker = (event_key, recipient_id)
            if marker in state.delivery_tracking_done or marker in state.delivery_tracking_enqueued:
                continue
            state.delivery_tracking_enqueued.add(marker)
            to_enqueue.append({"recipient_id": recipient_id, "url": url, "event_key": event_key, "payload": dict(event_payload)})

        for integration_id, integration in integrations:
            if event_payload["event"] not in integration.get("events", ["alert.fired", "alert.resolved"]):
                continue
            recipient_id = f"integration:{integration_id}"
            marker = (event_key, recipient_id)
            if marker in state.delivery_tracking_done or marker in state.delivery_tracking_enqueued:
                continue
            state.delivery_tracking_enqueued.add(marker)
            to_enqueue.append({
                "recipient_id": recipient_id,
                "url": integration["webhook_url"],
                "event_key": event_key,
                "payload": prepare_external_payload(integration, dict(event_payload)),
            })
            
    for item in to_enqueue:
        await queue.put(item)

async def event_dispatcher_loop() -> None:
    queue = state.dispatch_buffer
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
                        target = url
                        redirects = 0
                        while True:
                            resp = await client.post(target, json=payload, headers={"Content-Type": "application/json"})
                            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers and redirects < 5:
                                loc = resp.headers["location"]
                                if loc.startswith("/"):
                                    p = httpx.URL(target)
                                    loc = str(p.copy_with(path=loc, query=None, fragment=None))
                                target = loc
                                redirects += 1
                                continue
                            break
                        if 200 <= resp.status_code < 300:
                            with state.app_mutex:
                                state.delivery_tracking_enqueued.discard(marker)
                                state.delivery_tracking_done.add(marker)
                                state.operational_stats["webhook_deliveries"] += 1
                            break
                        if resp.status_code in (500, 502, 503, 504):
                            await asyncio.sleep(backoff_s)
                            backoff_s = min(backoff_s * 2.0, 30.0)
                            continue
                        with state.app_mutex:
                            state.delivery_tracking_enqueued.discard(marker)
                            state.delivery_tracking_done.add(marker)
                        break
                    except httpx.RequestError:
                        await asyncio.sleep(backoff_s)
                        backoff_s = min(backoff_s * 2.0, 30.0)
            finally:
                queue.task_done()
