"""
QuikScore API Request Logger Middleware
Logs all requests for scraper detection and security monitoring

Logs:
- Request details (timestamp, IP, method, path, user-agent, referer, query params)
- Response status code and duration
- Output to logs/scraper_detection.log

Useful for:
- Detecting scraping patterns
- Security audits
- Performance monitoring
- Debugging
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from datetime import datetime
import json

# ============================================================================
# SCRAPER DETECTION LOGGER SETUP
# ============================================================================
logger = logging.getLogger("scraper_detection")
logger.setLevel(logging.INFO)

# Ensure logs directory exists (skip on read-only filesystems like Render build)
import os
try:
    os.makedirs("logs", exist_ok=True)
    # File handler for scraper detection logs
    file_handler = logging.FileHandler("logs/scraper_detection.log")
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    logger.addHandler(file_handler)
except (OSError, PermissionError):
    # Skip file logging on read-only filesystems (Render build environment)
    pass

# Also log to console for development
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.addHandler(console_handler)


# ============================================================================
# REQUEST LOGGER MIDDLEWARE
# ============================================================================
class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all requests for security monitoring
    
    Features:
    - Logs request details (IP, method, path, user-agent, etc.)
    - Logs response status and duration
    - Outputs to logs/scraper_detection.log
    - Helps detect scraping patterns
    """
    
    async def dispatch(self, request: Request, call_next):
        start_time = datetime.now()
        
        # Extract request details
        log_entry = {
            "timestamp": start_time.isoformat(),
            "ip": request.client.host if request.client else "unknown",
            "method": request.method,
            "path": request.url.path,
            "user_agent": request.headers.get("user-agent", "unknown"),
            "referer": request.headers.get("referer", ""),
            "query_params": dict(request.query_params),
        }
        
        # Log request
        logger.info(f"REQUEST: {json.dumps(log_entry)}")
        
        # Process request
        response = await call_next(request)
        
        # Log response
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"RESPONSE: {request.url.path} - {response.status_code} - {duration:.3f}s")
        
        return response
