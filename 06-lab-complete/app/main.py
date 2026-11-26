"""
Production AI Agent — Part 6 Final Project

12 tiêu chí (xem README.md) — kiểm tra bằng:
    python check_production_ready.py

Luồng xử lý POST /ask:
    verify_api_key (401) → check_rate_limit (429, Redis) → check_budget (402, Redis)
    → gọi LLM (mock) → record_cost (Redis) → trả lời
"""
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r as redis_conn
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10): mỗi dòng log = 1 JSON object
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    _RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "pid": record.process,
        }
        # Các field truyền qua extra={...}
        for key, value in vars(record).items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("agent")
    log.setLevel(settings.log_level if settings.log_level in logging._nameToLevel else "INFO")
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        log.addHandler(handler)
    log.propagate = False
    return log


logger = _setup_logger()

START_TIME = time.time()
INSTANCE_ID = os.getenv("INSTANCE_ID", f"agent-{uuid.uuid4().hex[:6]}")
_state = {"ready": False, "in_flight": 0}


# ─────────────────────────────────────────────────────────
# Lifespan + graceful shutdown (tiêu chí 11)
# uvicorn bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong, rồi
# chạy phần sau `yield` bên dưới và thoát với exit code 0. Không tự ghi đè
# handler SIGTERM để khỏi chặn mất handler của uvicorn.
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={"event": "startup", "instance": INSTANCE_ID,
                                  "env": settings.environment, "port": settings.port,
                                  "redis_ok": redis_healthy()})
    _state["ready"] = True
    yield
    _state["ready"] = False
    logger.info("shutdown", extra={"event": "shutdown", "instance": INSTANCE_ID,
                                   "in_flight": _state["in_flight"]})
    try:
        redis_conn.close()
    except Exception:
        pass
    logger.info("shutdown complete", extra={"event": "shutdown_complete"})


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    _state["in_flight"] += 1
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Served-By"] = INSTANCE_ID
        return response
    finally:
        _state["in_flight"] -= 1
        logger.info("request", extra={
            "event": "request", "method": request.method, "path": request.url.path,
            "status": status, "ms": round((time.perf_counter() - started) * 1000, 1),
        })


# Xử lý lỗi: trả mã lỗi rõ ràng, không lộ stack trace
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "msg": e.get("msg")}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": "Invalid request", "details": errors})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled error", extra={"event": "error", "path": request.url.path,
                                           "error_type": type(exc).__name__})
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=128)


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"app": "Production AI Agent", "version": "1.0.0",
            "endpoints": ["GET /health", "GET /ready", "POST /ask (X-API-Key)"]}


@app.get("/health")
def health():
    """Liveness (tiêu chí 4): luôn 200 khi process còn chạy, không phụ thuộc Redis."""
    return {"status": "ok", "instance": INSTANCE_ID,
            "uptime_seconds": round(time.time() - START_TIME, 1),
            "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness (tiêu chí 5): 200 khi sẵn sàng; 503 khi đang tắt hoặc mất Redis."""
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail="Agent is starting up or shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not reachable")
    return {"status": "ready", "instance": INSTANCE_ID, "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    rate = check_rate_limit(api_key)          # 429 khi vượt RATE_LIMIT_PER_MINUTE
    check_budget()                            # 402 khi hết budget

    answer = llm_ask(body.question)

    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    logger.info("ask", extra={"event": "ask", "question_len": len(body.question),
                              "input_tokens": input_tokens, "output_tokens": output_tokens,
                              "cost_usd": cost})
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": cost, "requests_remaining": rate["remaining"]},
        "served_by": INSTANCE_ID,
    }
