# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được lấy trực tiếp từ các file JSON trong `reports/` (không ước lượng). Các mục Bước 2 cần Docker stack được đánh dấu rõ để bổ sung sau khi chạy trên máy có Docker Desktop.

**Họ tên:** Vũ Quang Hải (MSSV: `2A202603935`)  
**Ngày chạy:** 2026-11-26  
**Môi trường:** Windows, Python 3.12 (`.venv`), chạy local (Bước 1 — `06-lab-complete/benchmark-observability/develop/`)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Với mock LLM có độ trễ cơ bản ~120–180ms + retrieval ~20ms, ngưỡng 500ms đảm bảo trải nghiệm tương tác mượt cho 95% người dùng nhưng vẫn đủ biên độ cho biến động nhẹ. |
| Error rate `/ask` | `< 2.0 %` | Mock LLM có tỉ lệ lỗi upstream ~1%; đặt SLO 2% (error budget 2%) cho phép hấp thụ lỗi ngẫu nhiên nhỏ mà vẫn cảnh báo sớm khi upstream xuống cấp. |
| Accuracy trên golden dataset | `≥ 85 %` (mục tiêu sau sửa KB: `100 %`) | Đảm bảo agent v2 trả lời đúng phần lớn câu hỏi cốt lõi và chặn regression trong CI trước khi deploy. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Dữ liệu lấy từ `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` (`--requests 300`, SLO: p95 ≤ 500ms, error rate ≤ 2.0%):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.73 | 212.0 | 302.3 | 1724.0 | 2.33% | ❌ FAIL (error rate) |
| 10 | 40.64 | 208.6 | 325.1 | 1700.0 | 1.67% | ✅ PASS |
| 50 | 32.92 | 795.1 | 4437.3 | 6187.3 | 0.67% | ❌ FAIL (p95) |
| 100 | 23.97 | 2352.1 | 7086.1 | 10221.0 | 0.67% | ❌ FAIL (p95) |

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency. Từ `c=1` lên `c=10`, RPS tăng mạnh từ `3.73` lên `40.64 req/s` trong khi p50 gần như giữ nguyên (~210ms) vì server 1 worker vẫn còn dư năng lực xử lý bất đồng bộ (`asyncio`). Tuy nhiên từ `c=50` và `c=100`, hệ thống đạt bão hòa (event loop / socket / single uvicorn process trên Windows), hàng đợi request kéo dài khiến **RPS giảm ngược xuống** (`32.92` → `23.97 req/s`) còn **p95 tăng vọt** lên `4437.3 ms` và `7086.1 ms`.

### 2.2 Tail latency

Dữ liệu lấy từ `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` (`--requests 300 --concurrency 20`):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 236.5 | 524.6 | 573.8 |
| 0.03 (mặc định) | 293.9 | 580.7 | 1755.8 |
| 0.1 | 380.2 | 1709.1 | 1760.9 |

**Nhận xét:** **p99 và p95** là hai chỉ số nhạy nhất với request chậm:
- Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request chậm), **avg** chỉ tăng nhẹ từ `236.5 ms` lên `293.9 ms` (+24%), nhưng **p99** đã nhảy vọt gấp **3 lần** (`573.8 ms` → `1755.8 ms`).
- Khi tăng lên `0.1` (10% request chậm), **avg** mới ở mức `380.2 ms` (vẫn dưới 500ms!), nhưng **p95** đã vọt lên `1709.1 ms` (gấp 3.2 lần).
- Do đó **SLO không nên đặt theo average**, vì giá trị trung bình bị làm phẳng bởi đa số request nhanh và che giấu trải nghiệm rất tệ của 1–5% người dùng bị kẹt ở tail latency.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Dữ liệu lấy từ `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`:

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | 100.00% (23/23) |
| Avg tokens / câu | 56.6 | 109.3 | 113.7 |
| Tổng cost (USD) | $0.000397 | $0.000764 | $0.000790 |
| Cost / câu đúng (USD) | $0.00039735 | $0.00003639 | $0.00003436 |
| Quality gate | ❌ FAIL | ✅ PASS (≥ 80%, 0 regression) | ✅ PASS (≥ 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách đã sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` (từ khóa `["jwt"]`) giải thích JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn, khác với API key cố định. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` (từ khóa `["hpa", "kubernetes", "autoscal"]`) giải thích Kubernetes HPA scale pod dựa trên CPU, memory hoặc custom metrics (RPS, queue length). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- Agent v2 tốn gần gấp đôi token mỗi câu (`109.3`–`113.7` vs `56.6` tokens) và tổng chi phí cao hơn ~2 lần (`$0.000790` vs `$0.000397`) vì phải chèn thêm ngữ cảnh retrieval vào prompt, đồng thời thêm ~20ms độ trễ tìm kiếm tài liệu.
- Tuy nhiên, độ chính xác nhảy vọt từ `4.35%` lên `91.3%` (và `100%` sau khi bổ sung KB), làm cho **chi phí trên mỗi câu trả lời đúng (`cost / câu đúng`) giảm hơn 11 lần** (`$0.00039735` xuống `$0.00003436`). Đánh đổi chi phí/latency nhỏ để lấy chất lượng cao hơn nhiều lần là hoàn toàn xứng đáng.

---

## 4. Observability stack (production)

> **Lưu ý:** Phần 4 và Phần 5 yêu cầu Docker Compose stack (`06-lab-complete/benchmark-observability/production/`). Máy hiện tại chưa cài Docker nên chưa chạy được stack này. Cần chạy trên máy có Docker Desktop theo lệnh trong `CHECKPOINTS.md` (CP8) rồi điền số đo thực tế và ảnh chụp vào bảng dưới đây.

### 4.1 Screenshot

- [ ] `screenshots/grafana-dashboard.png` — Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] `screenshots/jaeger-slow-trace.png` — Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] `screenshots/jaeger-error-trace.png` — Một trace lỗi trong Jaeger (có event `exception`)
- [ ] `screenshots/prometheus-alert-firing.png` — Trang Alerts của Prometheus với ≥ 2 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `[Chờ đo với Docker stack]` | `[Chờ đo]` | Error rate (%) / LLM calls error |
| B | `MOCK_SLOW_RATE=0.3` | `[Chờ đo với Docker stack]` | `[Chờ đo]` | Latency p50/p95/p99 |
| C | `LLM_MODEL=mock-llm-large` | `[Chờ đo với Docker stack]` | `[Chờ đo]` | Cost USD/giờ & LLM p95 |
| D | `docker pause` 1 instance | `[Chờ đo với Docker stack]` | `[Chờ đo]` | Instances Up |
| E | `AGENT_VERSION=v1` | Không có | N/A | Retrieval hit ratio / Tokens/s / Agent version |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
- Các metric hạ tầng (RPS, HTTP 5xx, latency) vẫn xanh khi chất lượng câu trả lời giảm mạnh. Để phát hiện trong production cần kết hợp:
  1. **Eval quality gate trong CI/CD** trước khi deploy (so sánh accuracy với baseline trên golden dataset, chặn merge nếu tụt chất lượng hoặc có regression).
  2. **Online eval / LLM-as-a-judge trên mẫu traffic thật** (ví dụ lấy mẫu 5–10% request để chấm điểm chất lượng liên tục và cảnh báo khi điểm giảm).
  3. **Domain metrics & user feedback:** theo dõi `retrieval_hit_ratio` (alert khi tụt đột ngột về 0 như ở thí nghiệm E), tỉ lệ thumbs-down / retry của người dùng, và canary deployment để rollback tự động.

### 4.3 Debug bằng trace

> `[Chờ thu thập từ Jaeger và docker compose -p k5-day14-observability logs agent trên máy có Docker]`

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

> `[Chờ chạy Locust headless với --scale agent=1 và --scale agent=3 trên máy có Docker để tạo benchmark-results/scale_1_stats.csv và scale_3_stats.csv]`

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** `[Bổ sung phân tích sau khi có dữ liệu scale_1_stats.csv và scale_3_stats.csv]`

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Không dùng average làm SLO:** chỉ cần 3–10% request chậm là p95/p99 tăng gấp 3 lần trong khi trung bình vẫn có vẻ bình thường; phải dùng p95/p99.
  2. **Chất lượng phải đo bằng `cost / câu đúng` và quality gate tự động:** RAG (v2) tốn gấp đôi token nhưng rẻ hơn ~11 lần trên mỗi câu đúng; cần chạy eval so với baseline trong CI để chặn regression.
  3. **Hạ tầng xanh không đồng nghĩa với AI trả lời đúng:** cần kết hợp cả 3 trụ cột Observability (Metrics–Traces–Logs qua `trace_id`) lẫn đánh giá chất lượng (eval / retrieval hit ratio) để vận hành AI agent an toàn.
- **Nếu đưa agent này lên production thật, sẽ thêm metric / alert nào nữa?**
  - **Metric:** Time To First Token (TTFT) cho streaming, tỉ lệ hit cache/Redis, số lần kích hoạt rate limit (`429`) & cost guard (`402`), điểm online eval (faithfulness / relevance), và synthetic probe từ bên ngoài Nginx để bắt lỗi `502`/`504`.
  - **Alert:** cảnh báo `retrieval_hit_ratio` tụt bất thường, cảnh báo Redis down hoặc bộ nhớ Redis > 80%, và cảnh báo sớm khi chi tiêu đạt 80% ngân sách ngày/tháng.
