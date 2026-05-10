import asyncio
import threading
from typing import Any

# Global lock for thread-safe access to in-memory state
app_mutex = threading.Lock()

# Refs for background tasks
event_loop_ref: asyncio.AbstractEventLoop | None = None
probe_trigger: asyncio.Event | None = None
dispatch_buffer: asyncio.Queue[dict[str, Any]] | None = None
dispatcher_process: asyncio.Task[None] | None = None

# In-memory data stores
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

# Tracking for webhook deliveries
delivery_tracking_enqueued: set[tuple[str, str]] = set()
delivery_tracking_done: set[tuple[str, str]] = set()

# Operational metrics
operational_stats: dict[str, int] = {
    "total_checks": 0,
    "webhook_deliveries": 0,
}
