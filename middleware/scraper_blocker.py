"""
QuikScore API Scraper Blocker Middleware
Blocks known automated scraping User-Agents

Blocked patterns:
- python-requests, python-urllib
- curl/, wget/, scrapy/
- httpclient/, java/, okhttp/
- node-fetch/, go-http-client
- ruby/, perl/, php/

Returns 403 Forbidden for blocked User-Agents
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import logging

logger = logging.getLogger("scraper_detection")

# ============================================================================
# BLOCKED USER-AGENT PATTERNS
# ============================================================================
BLOCKED_USER_AGENTS = [
    'python-requests',
    'python-urllib',
    'curl/',
    'wget/',
    'scrapy/',
    'httpclient/',
    'java/',
    'okhttp/',
    'node-fetch/',
    'go-http-client',
    'ruby/',
    'perl/',
    'php/',
]


def is_blocked_user_agent(user_agent: str) -> bool:
    """
    Check if User-Agent matches known scraper patterns
    
    Args:
        user_agent: The User-Agent header value
        
    Returns:
        True if User-Agent should be blocked
    """
    if not user_agent:
        return True  # Block empty User-Agent
    
    ua_lower = user_agent.lower()
    return any(blocked in ua_lower for blocked in BLOCKED_USER_AGENTS)


# ============================================================================
# SCRAPER BLOCKER MIDDLEWARE
# ============================================================================
class ScraperBlockerMiddleware(BaseHTTPMiddleware):
    """
    Middleware to block automated scraping tools
    
    Features:
    - Blocks known scraper User-Agents
    - Blocks empty User-Agents
    - Logs blocked attempts
    - Returns 403 Forbidden with helpful message
    """
    
    async def dispatch(self, request: Request, call_next):
        # Skip blocker for public endpoints (health check, docs)
        public_paths = ['/', '/health', '/docs', '/redoc', '/openapi.json']
        if request.url.path in public_paths:
            return await call_next(request)
        
        # Skip OPTIONS requests (CORS preflight)
        if request.method == 'OPTIONS':
            return await call_next(request)
        
        # Extract User-Agent
        user_agent = request.headers.get("user-agent", "")
        
        # Check if User-Agent is blocked
        if is_blocked_user_agent(user_agent):
            client_host = request.client.host if request.client else "unknown"
            logger.warning(f"Blocked scraper: {user_agent} from {client_host}")
            
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Automated access not allowed. Please use our API.",
                    "error": "access_denied",
                    "message": "Automated tools and scripts are not permitted. Please contact us for API access."
                },
                headers={
                    "X-Blocked-Reason": "suspicious-user-agent",
                    "X-Contact": "api@quikscore.com"
                }
            )
        
        # User-Agent is OK, proceed with request
        response = await call_next(request)
        return response
