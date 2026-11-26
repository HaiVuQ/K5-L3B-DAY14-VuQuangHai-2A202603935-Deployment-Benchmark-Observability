# Day 14 Lab — Mission Answers

> **Họ tên:** Vũ Quang Hải · **MSSV:** `2A202603935` · **Lớp:** K5-L3B

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns tìm thấy trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong mã nguồn** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Khi push lên Git, secret bị lộ vĩnh viễn trong lịch sử commit.
2. **Hardcode cấu hình & bật `DEBUG = True` cố định** (dòng 21–22): không tách biệt cấu hình giữa dev/staging/production qua biến môi trường (vi phạm 12-Factor App).
3. **Dùng `print()` thay cho structured logging và log thẳng secret** (dòng 32–37): in ra `OPENAI_API_KEY` ở dòng 33 (`print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`), gây rò rỉ thông tin nhạy cảm và không thể lọc/tìm kiếm trong hệ thống log tập trung.
4. **Không có endpoint health check (`/health`, `/ready`)** (dòng 41–42): nền tảng cloud/load balancer không thể biết khi nào container bị treo hoặc chưa sẵn sàng nhận traffic.
5. **Bind `host="localhost"`, cố định `port=8000` và bật `reload=True`** (dòng 48–52): trong container phải bind `0.0.0.0` và đọc `PORT` từ biến môi trường; `reload=True` tốn tài nguyên và không ổn định trên production.
6. **Không có graceful shutdown**: khi container nhận `SIGTERM`, process bị tắt đột ngột, cắt ngang request đang xử lý (in-flight).

### Exercise 1.2: Kết quả chạy bản `develop`

Bản `develop` nhận `question` qua query parameter (`POST /ask?question=Hello`):

```http
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Kết quả kiểm tra bản `production` (`01-localhost-vs-production/production/app.py`):

```http
# GET /health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:46:53.471715+00:00"}

# GET /ready
HTTP/1.1 200 OK
{"ready":true}

# POST /ask (JSON body {"question":"Hello"})
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Tiêu chí | `develop/app.py` | `production/app.py` + `config.py` | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode trực tiếp (`OPENAI_API_KEY`, `DATABASE_URL`, dòng 17–18) | Đọc từ biến môi trường trong `config.py` (`Settings`, `os.getenv`, có `validate()` fail-fast khi thiếu `AGENT_API_KEY` ở production) | Tránh lộ secret trên Git; cùng 1 artifact chạy được ở dev/staging/prod theo nguyên tắc 12-Factor. |
| **Network & Port** | `host="localhost"`, `port=8000`, `reload=True` (dòng 49–51) | `host=settings.host` (`0.0.0.0`), `port=settings.port` (từ `PORT`), `reload=settings.debug` (dòng 256–260) | Container cần `0.0.0.0` mới nhận traffic từ ngoài; Railway/Render cấp `PORT` động. |
| **Health & Readiness** | Không có | `GET /health` (liveness + uptime) và `GET /ready` (trả `503` nếu `is_ready=False`, dòng 197–224) | Platform tự restart khi liveness fail; Load balancer chỉ đẩy traffic khi instance sẵn sàng. |
| **Logging** | `print()` thuần, lộ cả `OPENAI_API_KEY` (dòng 32–37) | `logging` xuất JSON có `time`, `level`, `msg`, không log secret (dòng 28–31, 173–184) | Dễ thu thập, tìm kiếm và tạo cảnh báo trên Datadog/Loki/ELK mà không làm lộ dữ liệu nhạy cảm. |
| **Shutdown** | Tắt đột ngột | `lifespan` chuyển `is_ready=False` khi tắt + đăng ký `SIGTERM` (dòng 39–65, 242–251) | Hoàn thành request đang xử lý trước khi thoát, tránh lỗi 502/504 cho người dùng khi deploy bản mới. |
| **Input & CORS** | Query param, không CORS | JSON body kiểm tra rỗng trả `422`, `CORSMiddleware` giới hạn origin và method (dòng 73–79, 165–171) | Kiểm soát đầu vào chặt chẽ và bảo vệ API khỏi truy cập cross-origin không mong muốn. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` (bản Python đầy đủ dựa trên Debian, dung lượng lớn ~1 GB vì chứa nhiều công cụ biên dịch và thư viện hệ thống).
2. **Working directory là gì?** `/app` (`WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó thực thi tương đối từ thư mục `/app`.
3. **Tại sao `COPY requirements.txt` trước `COPY . .` (hoặc `COPY app.py`)?** Để tận dụng **Docker build layer cache**. File `requirements.txt` ít thay đổi hơn source code; khi chỉ sửa code mà không đổi thư viện, Docker tái sử dụng lại layer `RUN pip install`, giúp build nhanh hơn rất nhiều.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `ENTRYPOINT` định nghĩa tiến trình chính cố định của container (khó bị ghi đè trừ khi truyền cờ `--entrypoint`).
   - `CMD` cung cấp lệnh mặc định hoặc tham số mặc định cho `ENTRYPOINT`, và dễ bị ghi đè khi truyền thêm đối số ở cuối lệnh `docker run <image> <command>`.

### Exercise 2.2 & 2.3: Multi-stage build & So sánh kích thước image

- **Stage 1 (`builder`, `FROM python:3.11-slim AS builder`):** cài công cụ build (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`, `FROM python:3.11-slim AS runtime`):** tạo non-root user (`appuser`), chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng mã nguồn, thêm `HEALTHCHECK` và chạy `uvicorn`.
- **Tại sao image nhỏ hơn?** Vì bỏ lại toàn bộ công cụ biên dịch (`gcc`, header files, apt cache, build artifacts) ở stage `builder`, đồng thời dùng base image `python:3.11-slim` thay vì `python:3.11` đầy đủ.

**Kết quả đo thực tế bằng `docker images | grep my-agent` (trên GitHub Codespaces, Docker 29.9.2):**
```text
my-agent:advanced    c95ae97bb825        240MB             57.7MB
my-agent:develop     d658f47e8250       1.67GB              427MB
```
- **Develop:** `1.67 GB` (~1670 MB)
- **Production (multi-stage):** `240 MB`
- **Chênh lệch:** giảm **`85.6%`** dung lượng image (nhỏ hơn ~7 lần).

### Exercise 2.4: Kiến trúc Docker Compose stack (`02-docker/production/docker-compose.yml`)

```text
                       ┌──────────────────────────┐
Client (HTTP :80) ───► │     nginx (alpine)       │  Reverse proxy, rate limit 10r/s,
                       │   ports: 80:80, 443:443  │  security headers, /health
                       └────────────┬─────────────┘
                                    │ network: internal (bridge)
                                    ▼
                       ┌──────────────────────────┐
                       │     agent (FastAPI)      │  target: runtime, không expose port
                       │       port 8000          │  env: REDIS_URL, QDRANT_URL
                       └─────┬──────────────┬─────┘
                             │              │
                  depends_on │              │ depends_on
              (healthy)      ▼              ▼ (healthy)
                 ┌──────────────────┐ ┌──────────────────┐
                 │  redis:7-alpine  │ │ qdrant:v1.9.0    │
                 │  port 6379       │ │ port 6333        │
                 │  vol: redis_data │ │ vol: qdrant_data │
                 └──────────────────┘ └──────────────────┘
```

- **Các service khởi động:** `nginx`, `agent`, `redis`, `qdrant` (4 service).
- **Cách giao tiếp:** Tất cả gắn vào chung bridge network `internal`. Các container gọi nhau bằng **tên service** qua Docker DNS nội bộ: Nginx proxy sang `http://agent:8000`, Agent nối tới `redis://redis:6379/0` và `http://qdrant:6333`. Chỉ `nginx` mở cổng ra host (`80`, `443`); `agent`, `redis`, `qdrant` được cô lập bên trong.
- **Kết quả test qua Nginx (`curl -sS http://localhost/health`):**
  ```json
  {"status":"ok","uptime_seconds":9.3,"version":"2.0.0","timestamp":"2026-11-26T09:51:03.557511"}
  ```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6 & So sánh `railway.toml` vs `render.yaml`

- **URL Public (agent Part 6 trên Render):** https://day14-production-agent-94oi.onrender.com
- **Platform:** Render Blueprint (`06-lab-complete/render.yaml` — Web Service Docker `day14-production-agent` + Key Value Redis `day14-agent-redis`, Free plan, Singapore)
- **Kết quả 4 lệnh tự kiểm CP6:** `/health` → `200`, `/ready` → `200` (`"redis":"ok"`), `/ask` không có key → `401`, `/ask` có `X-API-Key` → `200`
- **Screenshots:** [dashboard.png](screenshots/dashboard.png), [running.png](screenshots/running.png), [test.png](screenshots/test.png)

#### So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
|---|---|---|
| **Định dạng & phạm vi** | TOML, cấu hình **1 service** (build & deploy) tại thư mục hiện tại. | YAML, mô tả **nhiều service (IaC Blueprint)** trong cùng 1 file (cả Web Service lẫn Redis/KeyValue). |
| **Cách khai báo build** | `[build] builder = "DOCKERFILE"` (hoặc `NIXPACKS`) và `dockerfilePath`. | `runtime: docker` (hoặc `python`), hỗ trợ `rootDir`, `dockerfilePath`, `dockerContext` khi Dockerfile ở thư mục con. |
| **Quản lý biến môi trường & secret** | Không khai báo secret trong file; đặt qua Railway Dashboard hoặc CLI (`railway variables set`), tham chiếu Redis bằng `${{Redis.REDIS_URL}}`. | Khai báo trực tiếp mục `envVars:` trong YAML; secret dùng `sync: false` hoặc `generateValue: true`, nối Redis bằng `fromService`. |
| **Health check & restart** | `[deploy] healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries`. | `healthCheckPath: /health`, hỗ trợ cấu hình `plan`, `region`, `autoDeploy`. |
| **Điểm khác biệt chính** | Gọn nhẹ, thiên về cấu hình chạy từng service; hạ tầng phụ (Redis) tạo riêng trên dashboard. | Đầy đủ tính chất Infrastructure-as-Code: commit 1 file YAML là dựng đồng bộ cả web service + Redis + biến nối giữa chúng. |

### Exercise 3.3: Mô tả CI/CD Pipeline GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` tự động chạy 4 bước tuần tự (`waitFor`) khi push lên nhánh `main`:
1. **`test`:** dùng image `python:3.11-slim` cài dependencies và chạy `pytest tests/ -v --tb=short` — fail là dừng pipeline.
2. **`build`:** dùng `gcr.io/cloud-builders/docker` build Docker image gắn tag `$COMMIT_SHA` và `latest`, tận dụng `--cache-from` từ image `latest`.
3. **`push`:** đẩy toàn bộ tag image lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** dùng `gcloud run deploy` triển khai image `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`), cấu hình tài nguyên (`1 CPU`, `512Mi RAM`, `min-instances=1`, `max-instances=10`, `timeout=60s`) và gắn secret từ Google Secret Manager (`--set-secrets`). File `service.yaml` định nghĩa cấu hình tương đương theo chuẩn Knative IaC, bổ sung `containerConcurrency: 80`, `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu?** Hàm dependency `verify_api_key` dùng `APIKeyHeader(name="X-API-Key", auto_error=False)`, gắn vào `/ask` qua `Depends(verify_api_key)`.
- **Sai hoặc thiếu key:** thiếu header trả `401 Unauthorized`; sai key trong bản develop trả `403 Forbidden` (ở Part 6 chuẩn hóa cả hai trường hợp về `401` theo hợp đồng).
- **Cách rotate key:** không hardcode key; đặt key mới qua biến môi trường `AGENT_API_KEY` (trong production thực tế hỗ trợ danh sách 2 key active cùng lúc — key cũ và key mới — để chuyển đổi không downtime rồi thu hồi key cũ).

Kết quả chạy thực tế (`AGENT_API_KEY=secret-key-123`):

```http
# Không có X-API-Key → 401
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Có X-API-Key: secret-key-123 → 200
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Thuật toán rate limiting:** Sliding Window (dùng `deque` lưu timestamp các request trong 60 giây gần nhất; loại bỏ các timestamp cũ hơn `now - 60`).
- **Giới hạn:** `rate_limiter_user` = **10 req/phút** (`student`), `rate_limiter_admin` = **100 req/phút** (`teacher`).
- **Bypass/nâng giới hạn cho admin:** dựa vào claim `role` trong JWT (`if role == "admin"` chọn `rate_limiter_admin` thay vì `rate_limiter_user`, hoặc bỏ qua bước check).

Kết quả chạy thực tế với tài khoản `student` / `demo123` (`POST /auth/token` → `Bearer <REDACTED_TOKEN>`):

```http
# Gọi /ask không có token → 401
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Request #1 có Authorization: Bearer <REDACTED_TOKEN> → 200
HTTP/1.1 200 OK
content-type: application/json

{"question":"Test 1","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# Request #10 → 200 (requests_remaining về 0)
HTTP/1.1 200 OK
content-type: application/json

{"question":"Test 10","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000196}}

# Request #11 (vượt giới hạn 10 req/phút) → 429
HTTP/1.1 429 Too Many Requests
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost Guard

- **Tại sao cần cả Rate Limit lẫn Cost Guard?** Rate limit giới hạn **tốc độ** (số request/phút) để chống spam/DDoS, nhưng 1 request có prompt/output rất dài vẫn tốn rất nhiều token. Cost guard giới hạn **tổng chi phí (USD)** theo ngày/tháng để ngăn hóa đơn LLM vượt ngân sách.
- **Cách triển khai với Redis (đã cài đặt trong `06-lab-complete/app/cost_guard.py`):**
  1. **Trước khi gọi LLM (`check_budget`):** đọc tổng chi phí hiện tại từ Redis theo key `cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM`. Nếu vượt `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD`, trả ngay HTTP `402 Payment Required`.
  2. **Sau khi gọi LLM (`record_cost`):** tính chi phí dựa trên số token đầu vào/đầu ra (`input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K`), dùng `INCRBYFLOAT` cộng dồn atomic vào Redis và đặt `EXPIRE` (2 ngày cho daily, 32 ngày cho monthly) để tự reset chu kỳ mới.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Checks & Graceful Shutdown (`05-scaling-reliability/develop/app.py`)

Kết quả gọi thực tế:

```http
# GET /health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:47:13.110500+00:00","checks":{"memory":{"status":"ok","used_percent":76.4}}}

# GET /ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

- **Khác biệt giữa Liveness (`/health`) và Readiness (`/ready`):**
  - `/health` (liveness): kiểm tra **process còn sống không**. Nếu fail, platform sẽ **restart container**. Do đó `/health` không nên fail chỉ vì Redis tạm gián đoạn (nếu không mọi container sẽ bị restart hàng loạt).
  - `/ready` (readiness): kiểm tra **instance đã sẵn sàng nhận traffic chưa** (đã khởi động xong, chưa shutdown, kết nối được Redis). Nếu fail (`503`), load balancer tạm ngừng chuyển request tới instance đó nhưng **không restart**.
- **Graceful shutdown:** khi nhận `SIGTERM`, app chuyển cờ ready sang `False` (để LB ngừng gửi request mới), chờ các request in-flight hoàn thành, đóng kết nối Redis/DB rồi thoát với exit code `0`.

### Exercise 5.3 – 5.5: Stateless Design & Load Balancing (`05-scaling-reliability/production/`)

- **Vì sao state trong RAM bị hỏng khi chạy nhiều instance?** Khi Nginx phân phối request theo round-robin tới 3 instance (`agent-1`, `agent-2`, `agent-3`), request turn 1 có thể vào `agent-1` nhưng turn 2 vào `agent-2`. Nếu lịch sử hội thoại lưu trong dict RAM của `agent-1`, `agent-2` sẽ không thấy session đó.
- **Giải pháp stateless:** lưu toàn bộ session/history (và rate limit/cost ở Part 6) trong **Redis** với TTL (`setex("session:<id>", 3600, ...)`). Nhờ đó bất kỳ instance nào cũng đọc/ghi chung một nguồn sự thật.
- **Cơ chế `test_stateless.py`:** gửi 5 câu hỏi liên tiếp trong cùng một `session_id` qua Nginx (`http://localhost:8080/chat`), quan sát trường `served_by` thay đổi giữa các instance khác nhau, sau đó gọi `GET /chat/{session_id}/history` để xác nhận đủ 10 message (5 user + 5 assistant) vẫn nguyên vẹn nhờ Redis.
- **Kết quả chạy thực tế (`docker compose -p k5-day14-scaling up -d --build --scale agent=3` → `python test_stateless.py`):**
  ```text
  Session ID: 5c33a364-bada-424a-883e-8796e0217ff2
  Request 1: [instance-859a91]
  Request 2: [instance-50fe8d]
  Request 3: [instance-0d500d]
  Request 4: [instance-859a91]
  Request 5: [instance-50fe8d]
  Total requests: 5
  Instances used: {'instance-859a91', 'instance-50fe8d', 'instance-0d500d'}
  ✅ All requests served despite different instances!
  Total messages: 10
  ✅ Session history preserved across all instances via Redis!
  ```
  *(Nginx chia đều 5 request cho cả 3 instance khác nhau theo round-robin, và endpoint `/chat/{session_id}/history` vẫn đọc đủ 10 message vì toàn bộ session nằm trong Redis).*

---

## Part 6: Final Project (`06-lab-complete/`)

Đã hoàn thiện toàn bộ các file TODO trong `06-lab-complete/`:
- `app/config.py`, `app/auth.py`, `app/redis_client.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`
- `Dockerfile` (multi-stage `python:3.11-slim`, non-root `app`, `HEALTHCHECK`, `exec uvicorn` làm PID 1 lắng nghe `${PORT:-8000}`)
- `.dockerignore`, `docker-compose.yml` (`agent` + `redis:7-alpine`), `.env.example`, `railway.toml`, `render.yaml`

### Output `check_production_ready.py`

Chạy đầy đủ (có Docker + Redis + `--public-url https://day14-production-agent-94oi.onrender.com`) trên GitHub Codespaces (Linux `posix`, Docker 29.9.2):

```text
============================================================
📋 Checklist Deliverable
   ✅ Dockerfile (multi-stage, < 500 MB)
   ✅ docker-compose.yml (agent + redis)
   ✅ .dockerignore
   ✅ Health check endpoint (GET /health)
   ✅ Readiness endpoint (GET /ready)
   ✅ API Key authentication
   ✅ Rate limiting
   ✅ Cost guard
   ✅ Config từ environment variables
   ✅ Structured logging
   ✅ Graceful shutdown
   ✅ Public URL ready (Railway / Render config)
------------------------------------------------------------
Result: 12/12 tiêu chí đạt · 44/44 checks passed
🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
============================================================
```

*(Chi tiết nổi bật: Docker image `273 MB < 500 MB`, SIGTERM exit code `0`, `docker stop` tắt êm exit code `0` trong `0.6s`, Public URL `https://day14-production-agent-94oi.onrender.com/health` trả `200`).*

---

## Part 7: Ghi chú bài tập Exercise 7.1 & 7.3

### Exercise 7.1: Prometheus Metrics (`06-lab-complete/benchmark-observability/develop/app.py`)

1. **Ví dụ 3 loại metric trong `/metrics`:**
   - **Counter:** `http_requests_total{method="POST",route="/ask",status="200"} 1.0`
   - **Gauge:** `agent_in_flight_requests 0.0`
   - **Histogram:** `agent_question_length_chars_bucket{le="50.0"} 1.0` (và `http_request_duration_seconds_bucket`)
2. **Tại sao không dùng `request.url.path` làm label `route`?** Khi bot quét hàng nghìn URL ngẫu nhiên (`/wp-admin`, `/.env`, `/a1b2c3`...), mỗi URL lạ sẽ tạo ra một time series mới (**high cardinality**), khiến bộ nhớ RAM của Prometheus tăng vọt và có thể crash. Dùng `route.path` (route template) hoặc `"unmatched"` giữ số lượng time series cố định và nhỏ.
3. **Metric đã thêm:** Histogram `agent_question_length_chars` với buckets `(20, 50, 100, 200, 500, 1000, 2000)` trong `06-lab-complete/benchmark-observability/develop/app.py`.

### Exercise 7.3: CI Quality Gate

Đã tạo workflow GitHub Actions tại [`.github/workflows/eval.yml`](.github/workflows/eval.yml). Khi mở Pull Request:
- Workflow tự cài thư viện, chạy agent v2 ở chế độ `MOCK_ERROR_RATE=0` và gọi `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85`.
- Nếu accuracy < 85% hoặc có câu bị regression so với baseline, `run_eval.py` thoát với **exit code `1`** (đã kiểm chứng: chạy `v1` với `--baseline reports/eval_v2.json` trả về `exit_code = 1`, còn `v2_fixed` với `--min-accuracy 1.0` trả về `exit_code = 0`). GitHub Actions đánh dấu check FAIL và chặn merge PR.

### Exercise 7.4: Trả lời câu hỏi Observability stack (`production/`)

1. **p95 và avg:** trong đợt chạy bình thường (`scale_1`/`scale_3` với 100 users), avg `/ask` ~230ms và p95 ~220–250ms, nhưng p99 nhảy lên **1700ms** — khoảng cách lớn giữa avg/p50 và p99 phản ánh rõ 3% tail latency từ LLM. Khi bật `MOCK_SLOW_RATE=0.3` + `mock-llm-large`, p95 tăng vọt lên `1.91s` làm alert `AgentHighLatencyP95` firing.
2. **Nginx chia đều traffic:** Có — panel "Requests/s theo instance" trên Grafana (`screenshots/grafana-dashboard.png`) cho thấy Nginx phân phối tải đều cho các instance agent thông qua Docker DNS (`server agent:8000 resolve`).
3. **Vì sao input tokens/s lớn hơn output tokens/s?** Vì agent v2 dùng RAG: mỗi request gửi lên LLM bao gồm cả `SYSTEM_PROMPT` + ngữ cảnh tài liệu truy xuất từ `KNOWLEDGE_BASE` + câu hỏi người dùng (vd 83 input tokens vs 44 output tokens ở trace `2a24dc4ac82d0552a18ac08540f45728`).
4. **`curl -i http://localhost:8080/metrics` trả về gì và vì sao?** Trả về **`HTTP/1.1 404 Not Found`** vì `nginx.conf` chủ động chặn `/metrics` từ bên ngoài để không lộ thông tin nội bộ ra internet; chỉ Prometheus nằm cùng mạng Docker nội bộ mới scrape trực tiếp `agent:8000/metrics`.

---

## AI Log

| Hạng mục | Đã hỏi / yêu cầu AI gì | Nhận được gì | Tự kiểm tra & xác minh |
|---|---|---|---|
| Part 6 (`06-lab-complete/`) | Triển khai các module `config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` theo hợp đồng trong `06-lab-complete/README.md`. | Mã nguồn hoàn chỉnh dùng Redis sorted set cho sliding-window rate limit, Redis `INCRBYFLOAT` cho cost guard, `JsonFormatter` cho structured log, `lifespan` cho graceful shutdown và multi-stage Dockerfile. | Chạy `check_production_ready.py --public-url https://day14-production-agent-94oi.onrender.com` trên GitHub Codespaces đạt **`PASS 12/12` (44/44 checks passed)**. |
| Part 1, 2, 3, 4, 5 | Tổng hợp câu trả lời, deploy Blueprint lên Render và chạy kiểm thử Docker (Part 2, Part 5) trên Codespaces. | Kết quả đo thực tế: Render live + 4 lệnh CP6 (200/200/401/200), kích thước image `1.67GB` vs `240MB` (-85.6%), `test_stateless.py` chạy qua 3 instance giữ nguyên 10 message. | Tự xác minh trực tiếp trên Render Dashboard, curl từ máy local và output terminal Codespaces. |
| Part 7 (Bước 1 & Bước 2) | Thêm metric `agent_question_length_chars`, chạy load test + eval, sửa `KNOWLEDGE_BASE`, sửa lỗi thiếu `PYTHONUSERBASE` trong Dockerfile Part 7 production, chạy Locust scale 1 vs 3, kích hoạt alert & chụp ảnh Grafana/Jaeger/Prometheus. | 10 file `reports/*.json`, 2 file `benchmark-results/scale_*_stats.csv`, 4 ảnh Part 7 trong `screenshots/`, `eval_v2_fixed.json` đạt 23/23 (100%), 3 alert cùng firing, trace `2a24dc4ac82d0552a18ac08540f45728` khớp JSON log. | Đối chiếu 100% số liệu trong `BENCHMARK_REPORT.md` khớp từng file JSON/CSV; kiểm tra `promtool test rules` báo `SUCCESS`. |
