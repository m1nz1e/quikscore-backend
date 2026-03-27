"""
QuikScore API Rate Limiting Middleware
Per-user, tier-based rate limiting with proper headers

Tier Limits:
- FREE: 60 requests/hour (1 req/min average)
- STARTER: 60 requests/minute
- PRO: 120 requests/minute
- BUSINESS: 300 requests/minute

Returns 429 Too Many Requests when limit exceeded
Adds X-RateLimit-* headers to all responses
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Dict, Optional, Tuple
import time
from collections import defaultdict
import os

# Lazy import redis - only needed if REDIS_URL is configured
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False

# ============================================================================
# TIER-BASED RATE LIMIT CONFIGURATION
# ============================================================================
# Subscription tier limits (for authenticated users)
SUBSCRIPTION_LIMITS = {
    "free": {"requests": 60, "period": 3600},      # 60 req/hour
    "starter": {"requests": 60, "period": 60},     # 60 req/min
    "pro": {"requests": 120, "period": 60},        # 120 req/min
    "business": {"requests": 300, "period": 60},   # 300 req/min
}

# Anti-scraper tiered limits by authentication status
RATE_LIMITS = {
    'unauthenticated': 20,  # 20 req/min for anonymous users
    'authenticated': 60,    # 60 req/min for logged-in users
    'api_key': 300,         # 300 req/min for API key holders
}


def get_rate_limit_for_plan(plan: str) -> Dict[str, int]:
    """Get rate limit configuration for a subscription plan"""
    return SUBSCRIPTION_LIMITS.get(plan.lower(), SUBSCRIPTION_LIMITS["starter"])


def get_rate_limit_by_auth_status(auth_status: str) -> int:
    """
    Get rate limit by authentication status (anti-scraper tiered limits)
    
    Args:
        auth_status: One of 'unauthenticated', 'authenticated', 'api_key'
        
    Returns:
        Requests per minute limit
    """
    return RATE_LIMITS.get(auth_status, RATE_LIMITS['unauthenticated'])


# ============================================================================
# IN-MEMORY RATE LIMITER (Development/Fallback)
# ============================================================================
class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window
    Thread-safe for single-process deployments
    """
    
    def __init__(self):
        # Structure: {user_id: [(timestamp, count), ...]}
        self.requests: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, user_id: str, limit: int, period: int) -> Tuple[bool, int, int]:
        """
        Check if request is allowed under rate limit
        
        Returns:
            (allowed: bool, remaining: int, reset_time: int)
        """
        now = time.time()
        window_start = now - period
        
        # Clean old requests outside the window
        self.requests[user_id] = [
            ts for ts in self.requests[user_id]
            if ts > window_start
        ]
        
        # Count requests in current window
        current_count = len(self.requests[user_id])
        remaining = max(0, limit - current_count)
        reset_time = int(now) + period
        
        if current_count >= limit:
            return False, 0, reset_time
        
        # Record this request
        self.requests[user_id].append(now)
        
        return True, remaining - 1, reset_time  # -1 because we're about to make this request


# ============================================================================
# REDIS RATE LIMITER (Production)
# ============================================================================
class RedisRateLimiter:
    """
    Redis-based rate limiter for production
    Uses sliding window algorithm with sorted sets
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def is_allowed(self, user_id: str, limit: int, period: int) -> Tuple[bool, int, int]:
        """
        Check if request is allowed using Redis
        
        Returns:
            (allowed: bool, remaining: int, reset_time: int)
        """
        now = time.time()
        window_start = now - period
        key = f"ratelimit:{user_id}"
        
        # Use Redis pipeline for atomicity
        async with self.redis.pipeline() as pipe:
            # Remove old entries outside the window
            pipe.zremrangebyscore(key, 0, window_start)
            # Count current requests
            pipe.zcard(key)
            results = await pipe.execute()
        
        current_count = results[1]
        reset_time = int(now) + period
        
        if current_count >= limit:
            return False, 0, reset_time
        
        # Add this request with unique member (timestamp + nanoseconds)
        async with self.redis.pipeline() as pipe:
            pipe.zadd(key, {f"{now}:{time.time_ns()}": now})
            pipe.expire(key, period)
            await pipe.execute()
        
        remaining = limit - current_count - 1
        return True, remaining, reset_time


# ============================================================================
# RATE LIMIT MIDDLEWARE
# ============================================================================
class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware for QuikScore API
    
    Features:
    - Per-user rate limiting (not global)
    - Tier-based limits (FREE, STARTER, PRO, BUSINESS)
    - Redis-backed for production (survives restarts)
    - In-memory fallback for development
    - Standard rate limit headers on all responses
    """
    
    def __init__(self, app, redis_url: Optional[str] = None):
        super().__init__(app)
        
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self.limiter = InMemoryRateLimiter()
        self.redis_client = None
        
        # Try to connect to Redis (only if redis is available)
        if self.redis_url and REDIS_AVAILABLE:
            try:
                import asyncio
                self.redis_client = redis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    socket_keepalive=False,
                    retry_on_timeout=False
                )
                # Test connection
                asyncio.get_event_loop().run_until_complete(
                    asyncio.wait_for(self.redis_client.ping(), timeout=2.0)
                )
                self.limiter = RedisRateLimiter(self.redis_client)
                print("[RATE LIMIT] ✅ Redis connected - using production rate limiting")
            except Exception as e:
                print(f"[RATE LIMIT] ⚠️ Redis unavailable ({e.__class__.__name__}), using in-memory fallback")
                self.redis_client = None
        else:
            if not REDIS_AVAILABLE:
                print("[RATE LIMIT] ℹ️ Redis package not installed, using in-memory rate limiting")
            else:
                print("[RATE LIMIT] ℹ️ No Redis URL configured, using in-memory rate limiting")
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for public endpoints
        public_paths = ["/", "/health", "/docs", "/redoc", "/openapi.json"]
        if request.url.path in public_paths:
            return await call_next(request)
        
        # Skip OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # Extract user ID from request state (set by auth middleware)
        user_id = getattr(request.state, 'user_id', None)
        user_tier = getattr(request.state, 'user_tier', 'starter')
        
        # Determine rate limit tier based on authentication status (anti-scraper)
        auth_header = request.headers.get("authorization")
        if auth_header:
            auth_status = 'authenticated'
            limit = RATE_LIMITS['authenticated']  # 60 req/min
        else:
            auth_status = 'unauthenticated'
            limit = RATE_LIMITS['unauthenticated']  # 20 req/min (stricter for anonymous)
        
        # If no user info, use IP-based limiting with unauthenticated rate
        if not user_id:
            # Use client IP as identifier
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                user_id = forwarded_for.split(",")[0].strip()
            else:
                user_id = request.client.host if request.client else "anonymous"
        
        # Use subscription tier limits if user is authenticated (more permissive)
        if user_id and auth_status == 'authenticated':
            rate_config = get_rate_limit_for_plan(user_tier)
            limit = rate_config["requests"]
            period = rate_config["period"]
        else:
            # Use anti-scraper limits for unauthenticated users
            period = 60  # 1 minute window
        
        # Check rate limit
        if isinstance(self.limiter, InMemoryRateLimiter):
            allowed, remaining, reset_time = self.limiter.is_allowed(user_id, limit, period)
        else:
            allowed, remaining, reset_time = await self.limiter.is_allowed(user_id, limit, period)
        
        # Prepare rate limit headers
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(0, remaining)),
            "X-RateLimit-Reset": str(reset_time),
        }
        
        if not allowed:
            # Rate limit exceeded
            headers["Retry-After"] = str(period)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "error": "too_many_requests",
                    "message": f"You have exceeded your rate limit of {limit} requests per {period} seconds",
                    "tier": user_tier,
                    "limit": limit,
                    "retry_after": period
                },
                headers=headers
            )
        
        # Proceed with request
        response = await call_next(request)
        
        # Add rate limit headers to response
        for key, value in headers.items():
            response.headers[key] = value
        
        return response
