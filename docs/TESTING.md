# ProxyMaze'26 - Testing & Validation Guide

Complete guide to validate your ProxyMaze implementation before submission.

---

## Prerequisites

```bash
# Terminal 1: Run the service
cd "Proxy 26"
python -m uvicorn proxymaze.app:app --reload

# Terminal 2: Run tests
python test_api.py

# Or use curl for manual testing
```

---

## Phase 1: Basic Functionality

### Test 1.1: Health Check

```bash
curl http://localhost:8000/health
```

**Expected Response:**

```json
{ "status": "ok" }
```

**What it validates:** Service is running

---

### Test 1.2: Configuration Management

**Set Config:**

```bash
curl -X POST http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{
    "check_interval_seconds": 5,
    "request_timeout_ms": 2000
  }'
```

**Expected Response:** `{"status": "ok"}`

**Get Config:**

```bash
curl http://localhost:8000/config
```

**Expected Response:**

```json
{
  "check_interval_seconds": 5,
  "request_timeout_ms": 2000
}
```

**What it validates:**

- ✅ Config persists across requests
- ✅ Monitoring interval can be changed
- ✅ Timeout affects proxy checks

---

### Test 1.3: Proxy Pool Ingestion

**Add Proxies:**

```bash
curl -X POST http://localhost:8000/proxies \
  -H "Content-Type: application/json" \
  -d '{
    "proxies": [
      "https://httpbin.org/status/200",
      "https://httpbin.org/status/500"
    ],
    "replace": true
  }'
```

**Expected Response:**

```json
{
  "accepted": 2,
  "proxies": [
    {
      "id": "200",
      "url": "https://httpbin.org/status/200",
      "status": "pending"
    },
    {
      "id": "500",
      "url": "https://httpbin.org/status/500",
      "status": "pending"
    }
  ]
}
```

**What it validates:**

- ✅ ID extracted from last URL segment
- ✅ Status starts as "pending"
- ✅ Replace flag clears existing proxies

---

## Phase 2: Background Monitoring

**Wait 10 seconds for background monitoring to start**

### Test 2.1: Check Pool Status

```bash
curl http://localhost:8000/proxies
```

**Expected Response (after ~10 seconds):**

```json
{
  "total": 2,
  "up": 1,
  "down": 1,
  "failure_rate": 0.5,
  "proxies": [
    {
      "id": "200",
      "url": "https://httpbin.org/status/200",
      "status": "up",
      "last_checked_at": "2026-04-24T10:15:30Z",
      "consecutive_failures": 0
    },
    {
      "id": "500",
      "url": "https://httpbin.org/status/500",
      "status": "down",
      "last_checked_at": "2026-04-24T10:15:31Z",
      "consecutive_failures": 1
    }
  ]
}
```

**What it validates:**

- ✅ Proxies transitioned from "pending" to "up"/"down"
- ✅ HTTP 200 → up
- ✅ HTTP 500 → down
- ✅ failure_rate calculated correctly
- ✅ Background monitoring running

---

### Test 2.2: Single Proxy Details

```bash
curl http://localhost:8000/proxies/200
```

**Expected Response:**

```json
{
  "id": "200",
  "url": "https://httpbin.org/status/200",
  "status": "up",
  "last_checked_at": "2026-04-24T10:15:30Z",
  "consecutive_failures": 0,
  "total_checks": 2,
  "uptime_percentage": 100.0,
  "history": [
    { "checked_at": "2026-04-24T10:15:30Z", "status": "up" },
    { "checked_at": "2026-04-24T10:15:35Z", "status": "up" }
  ]
}
```

**What it validates:**

- ✅ Check history is recorded
- ✅ Uptime percentage calculated
- ✅ Multiple checks recorded

---

### Test 2.3: Proxy History

```bash
curl http://localhost:8000/proxies/500/history
```

**Expected Response:**

```json
[
  { "checked_at": "2026-04-24T10:15:30Z", "status": "down" },
  { "checked_at": "2026-04-24T10:15:35Z", "status": "down" }
]
```

**What it validates:**

- ✅ Returns JSON array
- ✅ All checks recorded
- ✅ Timestamps are ISO 8601

---

## Phase 3: Alert System

### Test 3.1: Alert Should Fire (at 50% failure rate)

With the current setup (1 up, 1 down = 50% failure), alert should already be active.

```bash
curl http://localhost:8000/alerts
```

**Expected Response:**

```json
[
  {
    "alert_id": "alert-a1b2c3d4",
    "status": "active",
    "failure_rate": 0.5,
    "total_proxies": 2,
    "failed_proxies": 1,
    "failed_proxy_ids": ["500"],
    "threshold": 0.2,
    "fired_at": "2026-04-24T10:15:35Z",
    "resolved_at": null,
    "message": "Proxy pool failure rate exceeded threshold"
  }
]
```

**What it validates:**

- ✅ Alert fires at ≥ 20% failure rate
- ✅ Alert ID is stable
- ✅ failed_proxy_ids matches actual down proxies
- ✅ resolved_at is null while active

---

### Test 3.2: Alert Resolution

**Replace pool with all healthy proxies:**

```bash
curl -X POST http://localhost:8000/proxies \
  -H "Content-Type: application/json" \
  -d '{
    "proxies": [
      "https://httpbin.org/status/200",
      "https://httpbin.org/status/200"
    ],
    "replace": true
  }'
```

**Wait 10 seconds for monitoring...**

```bash
curl http://localhost:8000/proxies
# Should show: "failure_rate": 0.0
```

**Check alerts:**

```bash
curl http://localhost:8000/alerts
```

**Expected Response:**

```json
[
  {
    "alert_id": "alert-a1b2c3d4",
    "status": "resolved",
    "failure_rate": 0.5,  # Historical value
    "resolved_at": "2026-04-24T10:16:00Z",
    ...
  }
]
```

**What it validates:**

- ✅ Alert resolves when failure_rate < 20%
- ✅ resolved_at is set
- ✅ status changes to "resolved"

---

### Test 3.3: Re-breach (New Alert ID)

**Trigger another breach:**

```bash
curl -X POST http://localhost:8000/proxies \
  -H "Content-Type: application/json" \
  -d '{
    "proxies": [
      "https://httpbin.org/status/200",
      "https://httpbin.org/status/500",
      "https://httpbin.org/status/500",
      "https://httpbin.org/status/500"
    ],
    "replace": true
  }'
```

**Wait 10 seconds...**

```bash
curl http://localhost:8000/alerts
```

**Expected Response:**

```json
[
  {
    "alert_id": "alert-a1b2c3d4",  # First alert (historical)
    "status": "resolved",
    ...
  },
  {
    "alert_id": "alert-e5f6g7h8",  # NEW alert with different ID
    "status": "active",
    "failure_rate": 0.75,
    "failed_proxies": 3,
    "failed_proxy_ids": ["500", "500", "500"]
    ...
  }
]
```

**What it validates:**

- ✅ Fresh breach creates new alert_id
- ✅ Only ONE active alert
- ✅ Previous resolved alert stays in archive

---

## Phase 4: Webhook System

### Test 4.1: Register Webhook

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://webhook.site/unique-id"}'
```

**Expected Response:**

```json
{
  "webhook_id": "wh-a1b2c3d4",
  "url": "https://webhook.site/unique-id"
}
```

**What it validates:**

- ✅ Webhook registered
- ✅ Returns webhook_id

---

### Test 4.2: Webhook Receives alert.fired

With a webhook registered and an alert active, you should receive webhook notifications.

**Using webhook.site:**

1. Go to https://webhook.site
2. Copy your unique URL
3. Register as webhook (see 4.1)
4. Trigger alert (replace pool with failures)
5. Check webhook.site dashboard

**Expected Payload:**

```json
{
  "event": "alert.fired",
  "alert_id": "alert-abc123",
  "fired_at": "2026-04-24T10:20:00Z",
  "failure_rate": 0.75,
  "total_proxies": 4,
  "failed_proxies": 3,
  "failed_proxy_ids": ["500", "500", "500"],
  "threshold": 0.2,
  "message": "Proxy pool failure rate exceeded threshold"
}
```

**What it validates:**

- ✅ Webhooks are sent
- ✅ Payload matches spec
- ✅ Delivered within 60 seconds

---

### Test 4.3: Webhook Receives alert.resolved

**Fix the pool (back to healthy):**

```bash
curl -X POST http://localhost:8000/proxies \
  -H "Content-Type: application/json" \
  -d '{"proxies": ["https://httpbin.org/status/200"], "replace": true}'
```

**Wait 10 seconds...**

**Check webhook.site again**

**Expected Payload:**

```json
{
  "event": "alert.resolved",
  "alert_id": "alert-abc123",
  "resolved_at": "2026-04-24T10:25:00Z"
}
```

**What it validates:**

- ✅ alert.resolved events sent
- ✅ Minimal payload for resolved events

---

## Phase 5: State Consistency

### Test 5.1: Trigger Alert and Verify Consistency

**Setup: 50% failure rate**

```bash
curl -X POST http://localhost:8000/proxies \
  -H "Content-Type: application/json" \
  -d '{
    "proxies": [
      "https://httpbin.org/status/200",
      "https://httpbin.org/status/500"
    ],
    "replace": true
  }'
```

**Wait 10 seconds...**

**Collect data from all three sources:**

```bash
# Source 1: GET /proxies
curl http://localhost:8000/proxies | jq '.proxies[] | select(.status=="down") | .id'

# Source 2: GET /alerts
curl http://localhost:8000/alerts | jq '.[0].failed_proxy_ids'
```

**Expected:**

```
Source 1: ["500"]
Source 2: ["500"]
```

**What it validates:**

- ✅ All endpoints agree on failed_proxy_ids
- ✅ failed_proxies count matches
- ✅ total_proxies count matches
- ✅ threshold is consistent

---

## Phase 6: Operational Features

### Test 6.1: Metrics Endpoint

```bash
curl http://localhost:8000/metrics
```

**Expected Response:**

```json
{
  "total_checks": 50,
  "current_pool_size": 2,
  "active_alerts": 1,
  "total_alerts": 2,
  "webhook_deliveries": 5
}
```

**What it validates:**

- ✅ Metrics tracked
- ✅ Counters increment
- ✅ Observable operational state

---

### Test 6.2: Delete Pool (Keep Alerts)

```bash
curl -X DELETE http://localhost:8000/proxies
```

**Expected Status:** 204 No Content

**Verify alerts remain:**

```bash
curl http://localhost:8000/alerts
```

**Should still return alerts from before deletion**

**What it validates:**

- ✅ DELETE /proxies clears pool
- ✅ Alert history preserved
- ✅ Proper 204 response

---

## Phase 7: Bonus Features (Slack/Discord)

### Test 7.1: Register Slack Integration

```bash
curl -X POST http://localhost:8000/integrations \
  -H "Content-Type: application/json" \
  -d '{
    "type": "slack",
    "webhook_url": "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK",
    "username": "ProxyWatch",
    "events": ["alert.fired", "alert.resolved"]
  }'
```

**Expected Response:**

```json
{
  "id": "int-abc123",
  "type": "slack",
  "webhook_url": "https://hooks.slack.com/services/..."
}
```

**What it validates:**

- ✅ Slack integration registered (+10 pts)

---

### Test 7.2: Register Discord Integration

```bash
curl -X POST http://localhost:8000/integrations \
  -H "Content-Type: application/json" \
  -d '{
    "type": "discord",
    "webhook_url": "https://discord.com/api/webhooks/YOUR/WEBHOOK",
    "username": "ProxyWatch",
    "events": ["alert.fired", "alert.resolved"]
  }'
```

**Expected Response:**

```json
{
  "id": "int-def456",
  "type": "discord",
  "webhook_url": "https://discord.com/api/webhooks/..."
}
```

**What it validates:**

- ✅ Discord integration registered (+10 pts)

---

## Complete Test Checklist

```
Phase 1: Basic Functionality
  ☐ Health check returns {"status": "ok"}
  ☐ POST /config sets values
  ☐ GET /config returns set values
  ☐ POST /proxies accepts and returns proxies

Phase 2: Background Monitoring
  ☐ Proxies transition from "pending" to "up"/"down"
  ☐ HTTP 200 classified as "up"
  ☐ HTTP 500 classified as "down"
  ☐ last_checked_at is recent timestamp
  ☐ Check history recorded

Phase 3: Alert System
  ☐ Alert fires at ≥20% failure rate
  ☐ Alert resolves at <20% failure rate
  ☐ Only ONE active alert exists
  ☐ Fresh breach creates new alert_id
  ☐ Resolved alerts stay in archive

Phase 4: Webhooks
  ☐ Webhook registration works
  ☐ alert.fired events received
  ☐ alert.resolved events received
  ☐ Payload includes all required fields
  ☐ Delivered within 60 seconds

Phase 5: State Consistency
  ☐ GET /proxies, GET /alerts agree on failed_proxy_ids
  ☐ failed_proxies count correct
  ☐ total_proxies count consistent
  ☐ All sources report same failure_rate

Phase 6: Operational Features
  ☐ GET /metrics returns valid JSON
  ☐ Counters increment appropriately
  ☐ DELETE /proxies clears pool
  ☐ Alerts persist after DELETE

Phase 7: Bonus Features
  ☐ Slack integration registered
  ☐ Discord integration registered
  ☐ (Optional) Receive formatted Slack messages
  ☐ (Optional) Receive formatted Discord embeds

Final Validation
  ☐ All 12 endpoints working
  ☐ Background monitoring autonomous
  ☐ State machine enforced
  ☐ No duplicate alerts
  ☐ Webhook delivery guaranteed
```

---

## Troubleshooting

### Issue: Proxies stuck in "pending"

**Diagnosis:**

```bash
curl http://localhost:8000/proxies | grep status
```

**Check 1:** Is monitoring running?

```bash
# Look for monitoring task output in terminal
```

**Check 2:** Are proxy URLs valid?

```bash
curl https://httpbin.org/status/200  # Should work
```

**Check 3:** Is timeout too short?

```bash
curl -X POST http://localhost:8000/config \
  -d '{"request_timeout_ms": 5000}'
```

---

### Issue: Alerts not firing

**Check 1:** Is failure_rate really ≥ 20%?

```bash
curl http://localhost:8000/proxies | jq '.failure_rate'
```

**Check 2:** Check alert history

```bash
curl http://localhost:8000/alerts
```

**Check 3:** Wait long enough

```bash
# Default interval is 15 seconds, wait at least that long
sleep 20
curl http://localhost:8000/proxies
```

---

### Issue: Webhooks not delivering

**Check 1:** Is webhook registered?

```bash
curl http://localhost:8000/webhooks  # This endpoint doesn't exist, use metrics
curl http://localhost:8000/metrics | grep webhook
```

**Check 2:** Is there an active alert?

```bash
curl http://localhost:8000/alerts | grep '"status": "active"'
```

**Check 3:** Check webhook URL is accessible

```bash
# Test from your service:
curl -X POST https://your-webhook-url.com \
  -H "Content-Type: application/json" \
  -d '{"test": true}'
```

---

## What You're Testing

| Test               | Validates           | Points |
| ------------------ | ------------------- | ------ |
| Health/Config      | Service bootstrap   | 10     |
| Proxy ingestion    | Pool management     | 45     |
| Status transitions | Real HTTP probes    | 30     |
| Alert firing       | Threshold detection | 90     |
| Alert resolution   | Threshold recovery  | 20     |
| Re-breach          | Alert lifecycle     | 30     |
| Metrics/Operations | Observability       | 25     |
| Slack/Discord      | Bonus integrations  | 20     |

**Total Tested:** 270 points ✅

---

Good luck! 🚀
