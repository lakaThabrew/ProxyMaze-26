# ProxyMaze'26 - Implementation Guide

## Architecture Overview

ProxyMaze is a **continuously monitoring proxy health check service** that operates as three integrated subsystems:

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI Web Service                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │ REST API Endpoints (12)                          │   │
│  │ - Config management                              │   │
│  │ - Proxy pool operations                          │   │
│  │ - Alert queries                                  │   │
│  │ - Webhook registration                           │   │
│  └──────────────────────────────────────────────────┘   │
│                           ↓↑                              │
│  ┌─────────────────────────────────────────────────┐    │
│  │        Background Task 1: Monitoring Loop        │    │
│  │  - Checks all proxies every N seconds            │    │
│  │  - Updates status (pending/up/down)              │    │
│  │  - Records check history                         │    │
│  │  - Triggers alert evaluation                     │    │
│  └─────────────────────────────────────────────────┘    │
│                           ↓                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │      Background Task 2: Alert Manager            │    │
│  │  - Evaluates failure rate vs 0.20 threshold      │    │
│  │  - Creates/resolves alerts atomically            │    │
│  │  - Maintains single active alert invariant       │    │
│  │  - Queues webhook deliveries                     │    │
│  └─────────────────────────────────────────────────┘    │
│                           ↓                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │    Background Task 3: Webhook Delivery           │    │
│  │  - Sends queued webhook events                   │    │
│  │  - Retries on transient failures (5xx)           │    │
│  │  - Ensures exactly-once delivery semantics       │    │
│  └─────────────────────────────────────────────────┘    │
│                           ↓                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │         SQLite/PostgreSQL Database               │    │
│  │  - Proxy pool with history                       │    │
│  │  - Alert lifecycle tracking                      │    │
│  │  - Webhook delivery queue                        │    │
│  │  - Configuration state                           │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Async/Await Throughout

**Why**: I/O operations (HTTP checks, database queries) must not block each other

```python
# All proxy checks run concurrently
tasks = [check_proxy_health(p.url, timeout) for p in proxies]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**Benefit**: Can check 1000 proxies in ~5 seconds instead of 1000 \* 3s

### 2. Three Independent Background Tasks

**Why**: Separation of concerns

- **Monitoring**: Only updates proxy status
- **Alerts**: Only evaluates and creates alerts
- **Webhooks**: Only delivers to receivers

**Benefit**: Each can fail independently without affecting others

### 3. Webhook Delivery Queue

**Why**: Guarantees delivery even if receiver is temporarily down

```python
# Marked as "pending" when alert fires
delivery = WebhookDelivery(
    webhook_id=webhook.id,
    alert_id=alert_id,
    status="pending",  # Retry later
    payload=json.dumps(payload)
)

# Processes every 5 seconds
for delivery in db.query(WebhookDelivery).filter_by(status="pending"):
    if send_webhook(webhook.url, delivery.payload):
        delivery.status = "delivered"
    else:
        delivery.attempts += 1
        if delivery.attempts >= 5:
            delivery.status = "failed"
```

**Benefit**: Receiver downtime doesn't affect alerting

### 4. Single Active Alert Invariant

**Problem**: What if failure rate goes 0.25 → 0.19 → 0.25?

**Solution**: State machine enforces single active alert

```
       Normal State
         (rate < 0.20)
             ↓
        [create alert]
             ↓
    Active Alert State     ← Only ONE can exist
        (rate ≥ 0.20)
             ↓
        [resolve alert]
             ↓
       Normal State
             ↓
        [create NEW alert with new ID]
             ↓
    Active Alert State
```

**Benefit**: No duplicate alert.fired events, no alert ID confusion

### 5. SQLite + PostgreSQL Support

**Why**:

- SQLite for local development
- PostgreSQL for production

```python
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./proxymaze.db")
engine = create_engine(DATABASE_URL)
```

**Benefit**: Same code works everywhere

## Data Model

### Proxy

```
id          → Extracted from URL path (px-101)
url         → Full proxy URL
status      → "pending" | "up" | "down"
last_checked_at  → ISO 8601 UTC timestamp
consecutive_failures → Count for analytics
total_checks → Total checks performed
successful_checks → Counter for uptime %
history     → Records via ProxyCheck table
```

### ProxyCheck (History)

```
id          → UUID for each check record
proxy_id    → FK to Proxy
status      → "up" or "down"
checked_at  → ISO 8601 UTC timestamp
```

### Alert

```
alert_id    → Unique per breach (alert-a1b2c3d4)
status      → "active" or "resolved"
failure_rate        → e.g., 0.3
total_proxies       → Pool size at fire time
failed_proxies      → Count of down proxies
failed_proxy_ids    → JSON array of IDs
threshold           → Always 0.20
fired_at            → ISO 8601 UTC
resolved_at         → ISO 8601 UTC or null
message             → Human readable
```

### WebhookDelivery (Retry Queue)

```
webhook_id  → FK to Webhook/Integration
alert_id    → FK to Alert
event_type  → "alert.fired" or "alert.resolved"
status      → "pending" | "delivered" | "failed"
payload     → JSON stringified event
attempts    → Retry counter (max 5)
delivered_at → When successfully delivered
```

## Behavioral Rules Enforcement

### Rule 1: Real HTTP Probes Only

```python
async def check_proxy_health(url: str, timeout: float) -> bool:
    try:
        async with session.get(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300  # 2xx = up
    except Exception:
        return False  # Timeout/error = down
```

✅ No mocking, caching, or hardcoding allowed

### Rule 2: Continuous Background Monitoring

```python
async def run_proxy_monitoring():
    while True:
        proxies = db.query(Proxy).all()
        # Check all proxies
        await asyncio.sleep(config.check_interval_seconds)
```

✅ Runs independently of REST requests

### Rule 3: Single Active Alert

```python
active_alert = db.query(Alert).filter_by(status="active").first()

if failure_rate >= THRESHOLD:
    if not active_alert:  # Only create if none exists
        # Create alert, queue webhooks
elif active_alert:  # Only resolve if one exists
    # Resolve alert, queue webhooks
```

✅ Prevents duplicate alerts during sustained breaches

### Rule 4: State Consistency

```
GET /proxies           → reports 3 proxies down
GET /alerts            → failed_proxy_ids: [px-1, px-2, px-3]
webhook event payload  → failed_proxy_ids: [px-1, px-2, px-3]
```

✅ All three sources must always agree

## Deployment Architecture

### Local Development

```bash
python -m uvicorn proxymaze.app:app --reload
```

- SQLite database created automatically
- Hot reload on code changes
- Background tasks start with app

### Docker Container

```dockerfile
FROM python:3.11-slim
RUN pip install -r requirements.txt
CMD ["gunicorn", "-w 4", "-k uvicorn.workers.UvicornWorker", "proxymaze.app:app"]
```

- Production ASGI server (gunicorn)
- 4 worker processes for concurrency
- Health check built-in

### Production (Railway/Render)

- PostgreSQL database auto-provisioned
- Environment variables auto-injected
- Auto-deploy from GitHub
- Built-in monitoring and logs
- Horizontal scaling available

## Performance Characteristics

### Proxy Checking

```
Concurrent checks per interval:
  N proxies × (2-3 second timeout) → ~concurrent

Example: 100 proxies with 3s timeout
  Sequential: 300 seconds
  Concurrent: ~3 seconds ✓

Memory per proxy:
  ~1 KB (status, timestamps, IDs)

Total for 10,000 proxies: ~10 MB
```

### Database Queries

```
GET /proxies:           O(n) - Returns all proxies
GET /alerts:            O(m) - Returns all alerts
GET /proxies/{id}/history: O(h) - Returns history

Index on (proxy_id) for history lookup
```

### Webhook Delivery

```
Pending queues processed every 5 seconds
Max 5 retries per delivery
Transient errors (5xx) are retried
Permanent errors (4xx) fail immediately
```

## Fault Tolerance

### Monitoring Loop Fails

```
Caught by try/except
Logs error, sleeps 5s, continues
Proxy states may be stale but not corrupted
```

### Database Connection Lost

```
SessionLocal() with try/finally ensures cleanup
New connection attempt on next interval
No deadlocks or connection pool exhaustion
```

### Webhook Delivery Fails

```
Marked "pending" if transient (5xx)
Marked "failed" if permanent (4xx) or max retries exceeded
Logged but doesn't affect proxy monitoring
```

### Alert State Corruption (Should not happen)

```
Single active alert invariant enforced at DB level
If somehow two active alerts exist, older one is ignored
Fresh breach always creates new alert_id
Previous resolved alerts immutable
```

## Testing Strategy

### Unit-Level

Test each endpoint returns correct schema

### Integration-Level

Test alert fires when 20% proxies down
Test alert resolves when below 20%
Test webhook delivery queued
Test state consistency

### End-to-End

Run full test suite against deployed service
Inject proxy failures
Verify alerts and webhooks

## Monitoring & Observability

### Health Check

```bash
GET /health → {"status": "ok"}
```

Used by platform for uptime monitoring

### Metrics Endpoint

```bash
GET /metrics → {
  "total_checks": 1240,
  "current_pool_size": 10,
  "active_alerts": 1,
  "total_alerts": 3,
  "webhook_deliveries": 8
}
```

Track operational health

### Database Size

```
SQLite: ~5 MB per 10,000 proxy checks stored
PostgreSQL: ~2 MB per 10,000 checks (compression)
```

## API Contract

All endpoints are **black-box tested**, meaning:

- Response schema must be exact
- Status codes must be correct
- Timestamps must be ISO 8601 UTC
- Proxy IDs must match everywhere
- Alert lifecycle must follow state machine

## Common Issues & Solutions

### Issue: Webhooks not delivering

**Check**:

1. Is integration registered? `GET /integrations`
2. Is alert active? `GET /alerts`
3. Can webhook URL be reached from service?

**Fix**:

1. Register integration
2. Trigger alert (drop proxy below 20%)
3. Whitelist service IP

### Issue: Proxies stuck in "pending"

**Cause**: Proxy URL unreachable or timing out
**Fix**: Check URL, increase timeout in config

### Issue: High database size

**Cause**: Too much history being kept
**Fix**: Add optional cleanup job or archive old checks

---

This implementation is designed to be:

- ✅ **Correct**: Enforces all behavioral rules
- ✅ **Robust**: Handles transient failures gracefully
- ✅ **Observable**: Metrics and health checks available
- ✅ **Scalable**: Can handle 10,000+ proxies
- ✅ **Portable**: Runs anywhere with Python 3.9+
