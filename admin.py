"""
QuikScore API Admin Endpoints
Security monitoring and scraper detection logs

Endpoints:
- GET /admin/scraper-logs - View recent scraper detection logs
- GET /admin/honeypot-triggers - View honeypot trigger logs

⚠️ These endpoints should be protected by authentication in production.
For now, they return logs but should be secured before deployment.
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import os
from datetime import datetime

router = APIRouter(prefix="/admin", tags=["admin"])

# ============================================================================
# ADMIN ENDPOINTS - SCRAPER LOGS
# ============================================================================

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)


@router.get("/scraper-logs")
async def get_scraper_logs(limit: int = 100):
    """
    View recent scraper detection logs (admin only)
    
    Args:
        limit: Maximum number of log entries to return (default: 100)
        
    Returns:
        List of recent log entries from scraper_detection.log
    """
    log_file = "logs/scraper_detection.log"
    
    try:
        if not os.path.exists(log_file):
            return {
                "logs": [],
                "message": "No logs yet",
                "log_file": log_file
            }
        
        with open(log_file, "r") as f:
            lines = f.readlines()[-limit:]
        
        return {
            "logs": [line.strip() for line in lines],
            "count": len(lines),
            "limit": limit,
            "log_file": log_file
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading logs: {str(e)}"
        )


@router.get("/honeypot-triggers")
async def get_honeypot_triggers(limit: int = 100):
    """
    View honeypot triggers (admin only)
    
    Args:
        limit: Maximum number of trigger entries to return (default: 100)
        
    Returns:
        List of recent honeypot trigger entries
    """
    log_file = "logs/honeypot_triggers.log"
    
    try:
        if not os.path.exists(log_file):
            return {
                "triggers": [],
                "message": "No triggers yet",
                "log_file": log_file
            }
        
        with open(log_file, "r") as f:
            lines = f.readlines()[-limit:]
        
        return {
            "triggers": [line.strip() for line in lines],
            "count": len(lines),
            "limit": limit,
            "log_file": log_file
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading honeypot logs: {str(e)}"
        )


@router.get("/security-summary")
async def get_security_summary():
    """
    Get a summary of security events
    
    Returns:
        Summary statistics from scraper and honeypot logs
    """
    scraper_log = "logs/scraper_detection.log"
    honeypot_log = "logs/honeypot_triggers.log"
    
    scraper_count = 0
    honeypot_count = 0
    last_scraper = None
    last_honeypot = None
    
    try:
        if os.path.exists(scraper_log):
            with open(scraper_log, "r") as f:
                lines = f.readlines()
                scraper_count = len(lines)
                if lines:
                    last_scraper = lines[-1].strip()
    except Exception:
        pass
    
    try:
        if os.path.exists(honeypot_log):
            with open(honeypot_log, "r") as f:
                lines = f.readlines()
                honeypot_count = len(lines)
                if lines:
                    last_honeypot = lines[-1].strip()
    except Exception:
        pass
    
    return {
        "scraper_detections": {
            "total": scraper_count,
            "last_event": last_scraper
        },
        "honeypot_triggers": {
            "total": honeypot_count,
            "last_event": last_honeypot
        },
        "generated_at": datetime.utcnow().isoformat()
    }
