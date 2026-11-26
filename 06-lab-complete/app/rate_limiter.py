"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) → mọi worker / instance dùng chung và vẫn
    còn sau khi restart agent.
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _redis_key(api_key: str) -> str:
    # Không lưu API key dạng plain text trong Redis
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    return f"ratelimit:{digest}"


def check_rate_limit(key: str) -> dict:
    limit = settings.rate_limit_per_minute
    now = time.time()
    rkey = _redis_key(key)
    try:
        # Bước 1 (atomic): xoá request cũ ngoài window rồi đếm
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(rkey, 0, now - WINDOW_SECONDS)
        pipe.zcard(rkey)
        _, count = pipe.execute()

        if count >= limit:
            oldest = r.zrange(rkey, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail={"error": "Rate limit exceeded", "limit": limit,
                        "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after),
                         "X-RateLimit-Limit": str(limit),
                         "X-RateLimit-Remaining": "0"},
            )

        # Bước 2: ghi nhận request này (member duy nhất để không trùng khi cùng timestamp)
        pipe = r.pipeline(transaction=True)
        pipe.zadd(rkey, {f"{now}:{uuid.uuid4().hex[:8]}": now})
        pipe.expire(rkey, WINDOW_SECONDS + 5)
        pipe.execute()
        return {"limit": limit, "remaining": max(0, limit - count - 1)}
    except redis.RedisError:
        # Redis chết → không thể đảm bảo giới hạn → từ chối (fail closed)
        raise HTTPException(status_code=503, detail="Rate limiter unavailable (Redis)")
