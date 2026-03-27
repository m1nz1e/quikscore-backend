"""
QuikScore API Honeypot Endpoints
Trap endpoints that only bots/scrapers will call

Legitimate users never call these endpoints:
- /admin/users
- /api/v2/companies
- /wp-admin
- /phpmyadmin
- /.env
- /backup.sql

Any request to these endpoints is flagged as suspicious and logged.
Returns 404 Not Found to pretend the endpoint doesn't exist.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime
import logging
import os

logger = logging.getLogger("scraper_detection")

router = APIRouter()

# ============================================================================
# HONEYPOT ENDPOINTS
# ============================================================================

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)


@router.get("/admin/users")
@router.get("/api/v2/companies")
@router.get("/wp-admin")
@router.get("/phpmyadmin")
@router.get("/.env")
@router.get("/backup.sql")
@router.get("/.git/config")
@router.get("/.aws/credentials")
@router.get("/config.php")
@router.get("/xmlrpc.php")
async def honeypot_endpoint(request: Request):
    """
    Honeypot endpoint - legitimate users never call this.
    Any request here is flagged as suspicious.
    
    Returns 404 to pretend the endpoint doesn't exist,
    but logs the attempt for security monitoring.
    """
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    logger.warning(f"🍯 HONEYPOT TRIGGERED: {client_host} - {user_agent} - {request.url.path}")
    
    # Log to honeypot triggers file
    with open("logs/honeypot_triggers.log", "a") as f:
        f.write(f"{datetime.now().isoformat()} - {client_host} - {user_agent} - {request.url.path}\n")
    
    # Return 404 (pretend endpoint doesn't exist)
    return JSONResponse(
        status_code=404,
        content={"detail": "Not found"}
    )
