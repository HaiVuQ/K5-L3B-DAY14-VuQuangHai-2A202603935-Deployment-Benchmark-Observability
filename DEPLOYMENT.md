# Deployment Information

> **Hướng dẫn hoàn thiện:** Deploy thư mục `06-lab-complete/` lên Railway hoặc Render (kèm 1 service Redis), sau đó thay `<YOUR-PUBLIC-URL>` bằng URL thật, chạy 4 lệnh kiểm tra ở dưới và chụp 3 ảnh lưu vào `screenshots/`.

## Public URL
https://<YOUR-PUBLIC-URL>

## Platform
Railway / Render (chọn nền tảng đã deploy từ `06-lab-complete/railway.toml` hoặc `06-lab-complete/render.yaml`)

## Test Commands

Đặt biến môi trường trước khi kiểm tra (không commit giá trị thật):

```bash
export BASE="https://<YOUR-PUBLIC-URL>"
export AGENT_API_KEY="<YOUR-API-KEY>"
```

### 4 lệnh tự kiểm (CP6)

```bash
# 1. Health check → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check (kiểm tra kết nối Redis trên cloud) → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. Gọi /ask không có API key → 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Gọi /ask có API key → 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

### Kiểm tra bằng script chấm

```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

## Environment Variables Set

Các biến môi trường đặt trên Dashboard của nền tảng (không ghi giá trị secret trong code hay file này):

- `PORT` (do nền tảng cấp tự động, mặc định `8000`)
- `ENVIRONMENT=production`
- `REDIS_URL` (trỏ tới Redis service trên cùng nền tảng)
- `AGENT_API_KEY` (secret, tạo mới trên Dashboard)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`
- `LOG_LEVEL=INFO`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
