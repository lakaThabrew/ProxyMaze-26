# PostgreSQL Setup Guide - Neon/Supabase

Complete guide to set up ProxyMaze with PostgreSQL using **Neon** or **Supabase**.

---

## 🚀 Option 1: Neon (Recommended for Speed)

Neon is a serverless PostgreSQL platform. Setup takes **2 minutes**.

### Step 1: Create Neon Account

1. Go to https://neon.tech
2. Click "Sign Up"
3. Create account (GitHub or email)

### Step 2: Create Project

1. Click "New Project"
2. Name: `proxymaze`
3. Region: Choose closest to you
4. PostgreSQL version: Latest (15+)
5. Click "Create Project"

### Step 3: Get Connection String

1. In Neon dashboard, click your project
2. Click "Connection strings" tab
3. Select "Pooled connection" (for Uvicorn)
4. Copy the connection string

**Format:**

```
postgresql://neon_user:password@project.neon.tech/proxymaze?sslmode=require
```

### Step 4: Set Environment Variable

**Local Development:**

```bash
# On Windows PowerShell
$env:DATABASE_URL="postgresql://neon_user:password@project.neon.tech/proxymaze?sslmode=require"

# Or create .env file
# DATABASE_URL=postgresql://neon_user:password@project.neon.tech/proxymaze?sslmode=require
```

**Windows Command Prompt:**

```cmd
set DATABASE_URL=postgresql://neon_user:password@project.neon.tech/proxymaze?sslmode=require
```

### Step 5: Start Service

```bash
python -m uvicorn proxymaze.app:app --reload
```

✅ **Done!** ProxyMaze now uses Neon PostgreSQL.

---

## 🚀 Option 2: Supabase (Recommended for Features)

Supabase combines PostgreSQL + real-time + auth + storage.

### Step 1: Create Supabase Account

1. Go to https://supabase.com
2. Click "Sign In"
3. Create account (GitHub)

### Step 2: Create Project

1. Click "New Project"
2. Name: `proxymaze`
3. Database password: Set strong password (save it!)
4. Region: Choose closest to you
5. Click "Create new project" (takes ~2 minutes)

### Step 3: Get Connection String

1. Go to Project Settings → Database
2. Scroll to "Connection string"
3. Copy the "URI" format

**Format:**

```
postgresql://postgres:password@db.project.supabase.co:5432/postgres?sslmode=require
```

### Step 4: Set Environment Variable

**PowerShell:**

```bash
$env:DATABASE_URL="postgresql://postgres:password@db.project.supabase.co:5432/postgres?sslmode=require"
```

**Command Prompt:**

```cmd
set DATABASE_URL=postgresql://postgres:password@db.project.supabase.co:5432/postgres?sslmode=require
```

### Step 5: Start Service

```bash
python -m uvicorn proxymaze.app:app --reload
```

✅ **Done!** ProxyMaze now uses Supabase PostgreSQL.

---

## 🔄 Local PostgreSQL (Docker)

For local development without cloud services.

### Step 1: Install Docker

Download from https://docker.com

### Step 2: Start PostgreSQL

```bash
docker run --name proxymaze-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=proxymaze \
  -p 5432:5432 \
  -d postgres:15
```

### Step 3: Set Environment Variable

**PowerShell:**

```bash
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/proxymaze"
```

**Or use docker-compose:**

```bash
docker-compose up -d
# Automatically sets DATABASE_URL for app service
```

### Step 4: Start Service

```bash
python -m uvicorn proxymaze.app:app --reload
```

✅ **ProxyMaze connected to local PostgreSQL**

---

## 📋 Connection String Format

All PostgreSQL providers use this format:

```
postgresql://[user]:[password]@[host]:[port]/[database][?options]
```

| Part     | Example            | Notes                                        |
| -------- | ------------------ | -------------------------------------------- |
| user     | `postgres`         | Database user                                |
| password | `secret123`        | Database password                            |
| host     | `db.neon.tech`     | Database host (cloud) or `localhost` (local) |
| port     | `5432`             | Default PostgreSQL port                      |
| database | `proxymaze`        | Database name                                |
| options  | `?sslmode=require` | Connection options (cloud requires SSL)      |

---

## 🧪 Verify Connection

### Test 1: Check Environment Variable

**PowerShell:**

```bash
$env:DATABASE_URL
# Should print your connection string
```

### Test 2: Test Database Connection

```bash
# Start the app
python -m uvicorn proxymaze.app:app --reload

# In another terminal
curl http://localhost:8000/health
# Should return {"status": "ok"}
```

### Test 3: Check Proxy List

```bash
curl http://localhost:8000/proxies
# Should return {"total": 0, "up": 0, "down": 0, "failure_rate": 0.0, "proxies": []}
```

---

## 🆘 Troubleshooting

### Error: "FATAL: password authentication failed"

**Cause:** Wrong password in connection string

**Fix:**

1. Go to your provider (Neon/Supabase)
2. Verify password matches
3. Update `DATABASE_URL`
4. Restart app

### Error: "could not translate host name"

**Cause:** Wrong hostname in connection string

**Fix:**

1. Copy full connection string from provider
2. Ensure no typos
3. Include `.neon.tech` or `.supabase.co` domain

### Error: "connection refused"

**Cause:** Database server not running (local PostgreSQL)

**Fix:**

```bash
# Check if Docker container running
docker ps | grep proxymaze-db

# If not, start it
docker run --name proxymaze-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=proxymaze \
  -p 5432:5432 \
  -d postgres:15
```

### Error: "SSL connection error"

**Cause:** Cloud provider requires SSL, but not configured

**Fix:** Add to connection string:

```
?sslmode=require
```

Example:

```
postgresql://user:pass@db.neon.tech/proxymaze?sslmode=require
```

---

## 🚀 Production Deployment

### Railway (Recommended)

1. Push to GitHub
2. Connect repo to Railway
3. Set environment variable in Railway dashboard:
   ```
   DATABASE_URL=postgresql://...
   ```
4. Deploy ✅

### Render

1. Push to GitHub
2. Connect repo to Render
3. Set environment variable:
   ```
   DATABASE_URL=postgresql://...
   ```
4. Deploy ✅

### Heroku

1. Create app: `heroku create proxymaze`
2. Set DATABASE_URL:
   ```bash
   heroku config:set DATABASE_URL=postgresql://...
   ```
3. Deploy:
   ```bash
   git push heroku main
   ```

---

## 💡 Provider Comparison

| Feature        | Neon       | Supabase          | Local           |
| -------------- | ---------- | ----------------- | --------------- |
| **Setup Time** | 2 min      | 3 min             | 5 min           |
| **Cost**       | Free tier  | Free tier         | Free (hardware) |
| **Ease**       | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐          | ⭐⭐⭐          |
| **Features**   | PostgreSQL | PostgreSQL + more | Full control    |
| **Best For**   | Speed      | Full stack        | Learning        |

---

## 📊 Performance Tips

### Index Configuration

ProxyMaze creates indexes automatically via SQLAlchemy models. No manual action needed.

### Connection Pooling

For local development, default pooling is fine.

For production with many concurrent requests:

**In your deployment platform settings:**

- Set connection pool size: 10-20
- Set pool timeout: 30 seconds
- Platform handles this automatically

### Monitoring

**Neon Dashboard:**

- View query performance
- Check active connections
- Monitor storage usage

**Supabase Dashboard:**

- Real-time metrics
- Query insights
- Connection monitoring

---

## 🔐 Security Best Practices

✅ **Never commit connection strings** to Git
✅ **Use environment variables** only
✅ **Enable SSL** (`?sslmode=require`)
✅ **Use strong passwords** (20+ characters)
✅ **Restrict IP access** if available
✅ **Enable backups** on production

---

## ⚡ Quick Commands

### Switch from SQLite to PostgreSQL

```bash
# 1. Get connection string from Neon/Supabase
# 2. Set environment variable
$env:DATABASE_URL="postgresql://..."

# 3. Restart app
python -m uvicorn proxymaze.app:app --reload
```

### Switch Back to SQLite

```bash
# 1. Remove DATABASE_URL environment variable
Remove-Item Env:DATABASE_URL

# 2. Restart app (uses SQLite by default)
python -m uvicorn proxymaze.app:app --reload
```

### View Current Database

```bash
# In Python
import os
print(os.getenv("DATABASE_URL", "SQLite: ./proxymaze.db"))
```

---

## 📚 Additional Resources

- **Neon Docs:** https://neon.tech/docs
- **Supabase Docs:** https://supabase.com/docs
- **PostgreSQL Docs:** https://www.postgresql.org/docs
- **SQLAlchemy ORM:** https://docs.sqlalchemy.org

---

## ✨ Next Steps

1. **Choose provider** (Neon recommended for speed)
2. **Create account** (2-3 minutes)
3. **Get connection string**
4. **Set DATABASE_URL** environment variable
5. **Start ProxyMaze**:
   ```bash
   python -m uvicorn proxymaze.app:app --reload
   ```
6. **Verify**:
   ```bash
   curl http://localhost:8000/health
   ```

---

**ProxyMaze now runs on enterprise PostgreSQL!** 🚀

From SQLite to PostgreSQL in under 5 minutes. That's the power of proper abstraction.

---

_ProxyMaze'26 - Torch Labs Monitoring System_
