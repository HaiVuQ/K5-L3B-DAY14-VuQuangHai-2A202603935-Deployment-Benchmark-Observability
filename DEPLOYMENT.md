# Deployment Information

## Public URL
https://day14-production-agent-94oi.onrender.com

## Platform
Render (Blueprint từ `06-lab-complete/render.yaml`: Docker Web Service `day14-production-agent` + Key Value / Redis `day14-agent-redis`, region Singapore, Free plan)

## Test Commands

Đặt biến môi trường trước khi kiểm tra (không commit giá trị thật):

```bash
export BASE="https://day14-production-agent-94oi.onrender.com"
export AGENT_API_KEY="<YOUR-API-KEY>"
```

### 4 lệnh tự kiểm (CP6)

```bash
# 1. Health check → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Output: 200

# 2. Readiness check (kiểm tra kết nối Redis trên cloud) → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Output: 200

# 3. Gọi /ask không có API key → 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Output: 401

# 4. Gọi /ask có API key → 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Output: 200
```

### Response mẫu `/health` và `/ready`

```json
// GET /health → 200
{"status":"ok","instance":"agent-ddd552","uptime_seconds":69.0,"environment":"production"}

// GET /ready → 200
{"status":"ready","instance":"agent-ddd552","redis":"ok"}
```

## Environment Variables Set

Các biến môi trường đặt qua Blueprint & Render Dashboard (không ghi giá trị secret trong code hay file này):

- `PORT` (Render cấp tự động, mặc định `8000`)
- `ENVIRONMENT=production`
- `REDIS_URL` (tự động nối tới internal connection string của `day14-agent-redis`)
- `AGENT_API_KEY` (`sync: false`, nhập trực tiếp trên Render Dashboard)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
