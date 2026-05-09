# Deployment Guide for ProxyMaze'26

## Quick Start: PostgreSQL Database Setup

Before deploying to a platform, you'll need a PostgreSQL database. Choose one:

### 🚀 Option 1: Neon (Recommended - 2 minutes)

Serverless PostgreSQL, perfect for ProxyMaze.

1. Go to https://neon.tech
2. Create account → Create project
3. Copy connection string (it looks like `postgresql://user:pass@project.neon.tech/proxymaze?sslmode=require`)
4. Save this for later (you'll set it as `DATABASE_URL`)

### 🚀 Option 2: Supabase (3 minutes)

PostgreSQL + extras (perfect if you want more features later).

1. Go to https://supabase.com
2. Create account → Create project
3. Go to Project Settings → Database → Connection string (URI format)
4. Copy the connection string
5. Save this for later (you'll set it as `DATABASE_URL`)

### 🚀 Option 3: Local Docker (For development)

```bash
docker run --name proxymaze-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=proxymaze \
  -p 5432:5432 \
  -d postgres:15
```

**See POSTGRESQL.md for complete PostgreSQL setup guide.**

---

## Local Development

### Prerequisites

- Python 3.9+
- pip
- (Optional) PostgreSQL connection string from Neon/Supabase

### Setup

```bash
# Clone/download the project
cd Proxy\ 26

# Install dependencies
pip install -r requirements.txt

# For local SQLite (default):
python -m uvicorn proxymaze.app:app --reload --host 0.0.0.0 --port 8000

# For PostgreSQL (set environment variable first):
# On Windows PowerShell:
$env:DATABASE_URL="postgresql://user:pass@project.neon.tech/proxymaze?sslmode=require"
python -m uvicorn proxymaze.app:app --reload --host 0.0.0.0 --port 8000
```

The service will be available at `http://localhost:8000`

---

## Deployment to Railway

Railway is the easiest platform for ProxyMaze - it auto-deploys from GitHub and handles scaling.

### Step 1: Create Railway Account

1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub

### Step 2: Create New Project

1. Click "Create New Project"
2. Select "Deploy from GitHub"
3. Connect your GitHub repository containing this code

### Step 3: Add PostgreSQL Database

1. Click "Add Service" → "PostgreSQL"
2. Railway creates a PostgreSQL database and auto-sets `DATABASE_URL`
3. Or use your own Neon/Supabase:
   - Go to Variables
   - Paste your Neon/Supabase connection string as `DATABASE_URL`

### Step 4: Configure Start Command

1. Go to your Web Service settings
2. Set Start Command:
   ```
   gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT proxymaze.app:app
   ```

### Step 5: Deploy

- Railway auto-deploys from your main branch
- Monitor logs in the Railway dashboard
- Your service is live! 🚀

**Pro Tip:** Use Neon's free tier for the database (it's better than Railway's PostgreSQL addon for cost).

---

## Deployment to Render

Render is a one-click deployment platform. It pairs well with external PostgreSQL (Neon/Supabase).

### Step 1: Create Render Account

1. Go to [render.com](https://render.com)
2. Sign up with GitHub

### Step 2: Create New Service

1. Click "New +" → "Web Service"
2. Select your GitHub repository
3. Configure:
   - **Name**: proxymaze
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT proxymaze.app:app`

### Step 3: Add Database Connection

**Option A: Use Neon (Recommended)**

1. Get your Neon connection string from https://neon.tech
2. In Render, go to "Environment"
3. Add environment variable:
   - **Key**: `DATABASE_URL`
   - **Value**: `postgresql://user:pass@project.neon.tech/proxymaze?sslmode=require`

**Option B: Use Supabase**

1. Get your Supabase connection string from https://supabase.com
2. In Render, go to "Environment"
3. Add environment variable:
   - **Key**: `DATABASE_URL`
   - **Value**: Your Supabase connection string

**Option C: Use Render's PostgreSQL (Less recommended)**

1. Click "Add Service" → "PostgreSQL"
2. Render will provide `DATABASE_URL` automatically

### Step 4: Deploy

- Save settings - Render auto-deploys on git push
- Monitor in Render dashboard
- Your service is live! 🚀

**Pro Tip:** Neon is cheaper and faster than Render's PostgreSQL. Pair Render's web service with Neon's database.

---

## Deployment to Heroku (Legacy)

Heroku is sunsetting, but still works. For new deployments, use Railway or Render instead.

### Step 1: Install Heroku CLI

```bash
# macOS
brew tap heroku/brew && brew install heroku

# Windows
# Download from https://devcenter.heroku.com/articles/heroku-cli
```

### Step 2: Login

```bash
heroku login
```

### Step 3: Create App

```bash
heroku create proxymaze-app
```

### Step 4: Configure Database

**Option A: Use Neon (Recommended)**

```bash
# Get your Neon connection string from https://neon.tech
heroku config:set DATABASE_URL="postgresql://user:pass@project.neon.tech/proxymaze?sslmode=require"
```

**Option B: Use Supabase**

```bash
# Get your Supabase connection string from https://supabase.com
heroku config:set DATABASE_URL="postgresql://user:pass@db.project.supabase.co:5432/postgres"
```

**Option C: Use Heroku PostgreSQL (Legacy)**

```bash
heroku addons:create heroku-postgresql:hobby-dev
```

### Step 5: Deploy

```bash
git push heroku main
```

### Step 6: View Logs

```bash
heroku logs --tail
```

---

## Summary: Recommended Stack

| Component      | Recommendation    | Why                           |
| -------------- | ----------------- | ----------------------------- |
| **Web App**    | Railway or Render | Auto-scaling, easy deployment |
| **Database**   | Neon              | Fast, cheap, serverless       |
| **Cost**       | ~$5-10/month      | Free tier available           |
| **Setup Time** | 5 minutes         | All one-click                 |

**Fastest Setup: Railway + Neon PostgreSQL**

- Railway: Deploy from GitHub with one click
- Neon: Create PostgreSQL in 2 minutes
- Total: 5 minutes to production

---

## Environment Variables Reference

### For Railway

Set in Railway dashboard → Variables:

```
DATABASE_URL=postgresql://...
PYTHONUNBUFFERED=1
```

### For Render

Set in Render dashboard → Environment:

```
DATABASE_URL=postgresql://...
PYTHONUNBUFFERED=1
```

### For Heroku

Set via CLI:

```bash
heroku config:set DATABASE_URL="postgresql://..."
heroku config:set PYTHONUNBUFFERED=1
```

### For Local Development

PowerShell:

```bash
$env:DATABASE_URL="postgresql://..."
$env:PYTHONUNBUFFERED=1
python -m uvicorn proxymaze.app:app --reload
```

---

## Monitoring Your Deployment

### Railway

- Go to railway.app dashboard
- Click your project
- Monitor "Logs" tab in real-time

### Render

- Go to render.com dashboard
- Click your service
- Monitor "Logs" tab

### Heroku

```bash
heroku logs --tail
```

---

## Getting Help

- **ProxyMaze Docs**: See README.md, IMPLEMENTATION.md, POSTGRESQL.md
- **Railway Docs**: https://docs.railway.app
- **Render Docs**: https://render.com/docs
- **Neon Docs**: https://neon.tech/docs
- **Supabase Docs**: https://supabase.com/docs

---

## Using Docker

### Local with Docker

```bash
# Build
docker build -t proxymaze .

# Run with SQLite
docker run -p 8000:8000 proxymaze

# Or use docker-compose with PostgreSQL
docker-compose up
```

### Push to Container Registry

#### Docker Hub

```bash
docker build -t yourusername/proxymaze .
docker push yourusername/proxymaze
```

#### GitHub Container Registry

```bash
docker build -t ghcr.io/yourusername/proxymaze .
docker push ghcr.io/yourusername/proxymaze
```

---

## Production Checklist

- [ ] Database is PostgreSQL (not SQLite)
- [ ] `DATABASE_URL` environment variable is set
- [ ] Use `gunicorn` with 4+ workers
- [ ] Enable health check endpoint monitoring
- [ ] Set up log aggregation (Railway/Render provide this)
- [ ] Monitor /metrics endpoint for operational health
- [ ] Configure uptime monitoring for /health endpoint
- [ ] Test webhook delivery in staging
- [ ] Set reasonable config values:
  ```json
  {
    "check_interval_seconds": 30,
    "request_timeout_ms": 5000
  }
  ```

---

## Monitoring in Production

### Health Check

```bash
curl https://your-service-url.com/health
```

### Metrics

```bash
curl https://your-service-url.com/metrics
```

### Logs

- Railway: View in dashboard
- Render: View in dashboard
- Heroku: `heroku logs --tail`

### Database

- Railway: Built-in metrics
- Render: Built-in metrics
- Heroku: Use `heroku pg:info`

---

## Troubleshooting

### Service won't start

- Check `DATABASE_URL` is valid
- Check Python version (3.9+)
- View logs for errors

### Proxies not monitoring

- Check `check_interval_seconds` in config
- Check if background tasks are running (logs should show startup)
- Verify proxy URLs are accessible from service location

### Webhooks not delivering

- Check webhook URL is accessible
- Check service logs for delivery errors
- Verify webhook receiver accepts POST with `Content-Type: application/json`

### Database connection issues

- Verify `DATABASE_URL` format
- Check database is running
- For PostgreSQL: verify user/password/host/port
- Try SQLite first for local testing

---

## Auto-Scaling Tips

- Railway: Scaling configured per plan
- Render: Set concurrent requests limit
- Heroku: Use dynos with autoscale

ProxyMaze is designed to handle hundreds of proxies on a single instance. If you need to scale:

1. Use read replicas for the database
2. Consider separating monitoring into a worker process
3. Use a message queue (Redis/RabbitMQ) for webhook delivery
