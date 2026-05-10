from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlparse
from typing import Any
from . import state

def trigger_immediate_probe() -> None:
    loop = state.event_loop_ref
    ev = state.probe_trigger
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
    for alert in reversed(state.alert_records):
        if alert.get("alert_id") == alert_id:
            return alert
    return None

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
        raise ValueError("proxy URL must have a non-empty last path segment used as id")
    return segment
