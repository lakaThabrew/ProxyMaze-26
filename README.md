# ProxyMaze'26 - Real-Time Proxy Monitoring Service

A continuously running proxy monitoring system that tracks proxy health, fires alerts, and delivers webhooks. Built for Torch Labs by the 2026 Engineering Challenge.

## Features

- ✅ **Continuous Background Monitoring** - Autonomous proxy health checks on configurable intervals
- ✅ **Alert Lifecycle Management** - Single active alert per breach, proper state transitions
- ✅ **Webhook Delivery with Retries** - Guaranteed delivery with transient error handling
- ✅ **Complete State Consistency** - All endpoints agree on pool status
- ✅ **Bonus Integrations** - Slack and Discord formatted alerts (+20 pts)
- ✅ **12 Endpoints** - Full operational contract implemented

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the Service

```bash
cd proxymaze
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The service will be available at `http://localhost:8000`

### 3. Test Health

```bash
curl http://localhost:8000/health
```

## API Endpoints

### Core Endpoints (Required)

| Endpoint                | Method          | Purpose               | Points   |
| ----------------------- | --------------- | --------------------- | -------- |
| `/health`               | GET             | Proof of life         | 10       |
| `/config`               | POST/GET        | Runtime configuration | -        |
| `/proxies`              | POST/GET/DELETE | Proxy pool management | 45+25    |
| `/proxies/{id}`         | GET             | Single proxy details  | -        |
| `/proxies/{id}/history` | GET             | Check history         | -        |
| `/alerts`               | GET             | Alert archive         | 90+20+30 |
| `/webhooks`             | POST            | Webhook registration  | -        |
| `/integrations`         | POST            | Slack/Discord setup   | +20      |
| `/metrics`              | GET             | Operational metrics   | 25       |

### Example: Add Proxies

```bash
curl -X POST http://localhost:8000/proxies \
  -H "Content-Type: application/json" \
  -d '{
    "proxies": [
      "https://proxy-provider.example/proxy/px-101",
      "https://proxy-provider.example/proxy/px-102"
    ],
    "replace": true
  }'
```

### Example: Register Webhook

```bash
curl -X POST http://localhost:8000/webhooks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-receiver.example/webhook"}'
```

### Example: Configure Monitoring

```bash
curl -X POST http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{
    "check_interval_seconds": 15,
    "request_timeout_ms": 3000
  }'
```

## Architecture

### Background Services

- **Monitoring Service**: Runs continuously, checks all proxies every `check_interval_seconds`
- **Alert Manager**: Evaluates failure rate against 0.20 threshold
- **Webhook Delivery**: Processes pending deliveries with retry logic

### Data Models

- **Proxy**: URL, status, check history, uptime stats
- **Alert**: Lifecycle managed, single active per breach
- **WebhookDelivery**: Guaranteed delivery with retry tracking
- **Config**: Runtime parameters

### Key Design Decisions

1. **Async/Await**: All I/O operations are non-blocking
2. **PostgreSQL Recommended**: Use Neon or Supabase for production (can use SQLite locally)
3. **Task-Based Scheduling**: Simpler than external schedulers for this use case
4. **Webhook Queue**: Decouples delivery from monitoring loop

## Behavioral Rules

✅ Monitoring runs **continuously** in the background  
✅ Proxy status derived from **real HTTP probes** only  
✅ 2xx response within timeout = **up**  
✅ Timeout/5xx response = **down**  
✅ Alert fires when failure_rate ≥ 0.20  
✅ Alert resolves when failure_rate < 0.20  
✅ **Only ONE active alert** at a time  
✅ After resolution, fresh breach = new alert_id  
✅ `failed_proxy_ids` always equals set of down proxies  
✅ All endpoints agree on state

## Webhook Payload Examples

### alert.fired

```json
{
  "event": "alert.fired",
  "alert_id": "alert-a1b2c3",
  "fired_at": "2026-04-24T10:20:00Z",
  "failure_rate": 0.3,
  "total_proxies": 10,
  "failed_proxies": 3,
  "failed_proxy_ids": ["px-103", "px-104", "px-105"],
  "threshold": 0.2,
  "message": "Proxy pool failure rate exceeded threshold"
}
```

### alert.resolved

```json
{
  "event": "alert.resolved",
  "alert_id": "alert-a1b2c3",
  "resolved_at": "2026-04-24T10:30:00Z"
}
```

## Scoring Breakdown

- Service bootstrap and config: **10 pts**
- Proxy pool ingestion: **45 pts**
- Single failure behavior: **30 pts**
- Threshold breach alerts: **90 pts**
- Alert resolution: **20 pts**
- Re-breach lifecycle: **30 pts**
- Pool operations: **25 pts**
- **Slack integration: +10 pts** (bonus)
- **Discord integration: +10 pts** (bonus)

**Total: 250 core + 20 bonus = 270 pts**  
**Passing: 186 pts**

## Deployment

### Local Development (SQLite)

```bash
python -m uvicorn proxymaze.app:app --reload
```

### Production (PostgreSQL + Railway/Render)

**Option 1: Neon (Fastest Setup - 2 minutes)**

1. Create account: https://neon.tech
2. Create project → Copy connection string
3. Set `DATABASE_URL` environment variable in Railway/Render
4. Deploy ✅

**Option 2: Supabase (More Features - 3 minutes)**

1. Create account: https://supabase.com
2. Create project → Copy connection string (URI format)
3. Set `DATABASE_URL` environment variable in Railway/Render
4. Deploy ✅

**See POSTGRESQL.md for complete setup guides.**

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string (Neon/Supabase recommended)
  - Neon: `postgresql://user:pass@project.neon.tech/db?sslmode=require`
  - Supabase: `postgresql://postgres:pass@db.project.supabase.co:5432/postgres`
- `PYTHONUNBUFFERED`: Set to `1` for real-time logging

## Testing Checklist

- [ ] Health check returns `{"status": "ok"}`
- [ ] Config accepts and returns monitoring parameters
- [ ] Proxies start as "pending" and transition to up/down
- [ ] Failure rate calculated correctly
- [ ] Alert fires at ≥20% failure rate
- [ ] Alert resolves at <20% failure rate
- [ ] Single active alert per breach
- [ ] Webhook deliveries are idempotent
- [ ] All endpoints agree on state
- [ ] DELETE /proxies clears pool but keeps alerts

## Bonus Features

### Slack Integration (+10 pts)

```bash
curl -X POST http://localhost:8000/integrations \
  -H "Content-Type: application/json" \
  -d '{
    "type": "slack",
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "username": "ProxyWatch",
    "events": ["alert.fired", "alert.resolved"]
  }'
```

### Discord Integration (+10 pts)

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

## Technical Notes

- All timestamps are ISO 8601 UTC (e.g., `2026-04-24T10:15:30Z`)
- Proxy IDs extracted from final URL segment
- Request bodies accept unknown fields without error
- Retry logic: 5 attempts max, 2-second fixed backoff
- Webhook delivery timeout: 10 seconds
- Max concurrent proxy checks: unlimited (per config)

---

**ProxyMaze'26**: Building the watchtower Torch Labs needed.  
Torch Labs • Colombo, Sri Lanka • From Sri Lanka, to the world.
