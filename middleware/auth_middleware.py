"""
Authentication Middleware for QuikScore API
Extracts user info from JWT tokens and sets it on request.state
Used by rate limiter to identify users and their tiers
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, Dict, Any
import jwt
import os
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

# Tier mapping - in production, this would come from database
# For now, we use a simple mapping. Authenticated users get STARTER by default.
DEFAULT_USER_TIER = "starter"


def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware that extracts user info from JWT tokens
    
    Sets on request.state:
    - user_id: User UUID from token
    - user_tier: Subscription tier (free, starter, pro, business)
    - email: User email from token
    - is_authenticated: Boolean flag
    
    Note: Full tier lookup from database is expensive for rate limiting.
    We use JWT claims or default tiers. For production, cache tier in JWT or Redis.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth for public endpoints
        public_paths = ["/", "/health", "/docs", "/redoc", "/openapi.json"]
        if request.url.path in public_paths:
            return await call_next(request)
        
        # Skip OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # Extract Authorization header
        auth_header = request.headers.get("Authorization", "")
        
        user_id = None
        user_tier = "free"  # Default to free tier for unauthenticated
        email = None
        is_authenticated = False
        
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            payload = decode_jwt_token(token)
            
            if payload:
                user_id = payload.get("sub")
                email = payload.get("email")
                is_authenticated = True
                
                # Check if tier is in JWT payload (optional)
                user_tier = payload.get("tier", DEFAULT_USER_TIER)
                
                # Normalize tier to lowercase
                user_tier = user_tier.lower()
                
                # Validate tier
                if user_tier not in ["free", "starter", "pro", "business"]:
                    user_tier = DEFAULT_USER_TIER
        
        # Set user info on request state for rate limiter
        request.state.user_id = user_id
        request.state.user_tier = user_tier
        request.state.email = email
        request.state.is_authenticated = is_authenticated
        
        # Proceed with request
        response = await call_next(request)
        return response
