"""
QuikScore Authentication System
Complete SaaS auth with JWT, sessions, and security
"""

from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import jwt
import bcrypt
import os
import uuid
from databases import Database
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24
PASSWORD_RESET_EXPIRY_HOURS = 24

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/quikscore")
database = Database(DATABASE_URL)

# Security
security = HTTPBearer()

# Pydantic models
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str
    company_name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    company_name: Optional[str]
    subscription_tier: str
    subscription_status: str
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: UserResponse

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

class TokenVerify(BaseModel):
    valid: bool
    user: Optional[UserResponse]
    expires_at: Optional[datetime]

# Helper functions
def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_jwt_token(user_id: str, email: str, expires_delta: timedelta) -> str:
    """Create JWT token"""
    expire = datetime.utcnow() + expires_delta
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """Get current user from JWT token"""
    token = credentials.credentials
    payload = decode_jwt_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return payload

# Routes
@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserRegister):
    """
    Register a new user account
    
    - **email**: User email (must be unique)
    - **password**: Password (min 8 characters)
    - **name**: User's full name
    - **company_name**: Optional company name
    """
    await database.connect()
    
    try:
        # Check if user exists
        query = "SELECT id FROM users WHERE email = :email"
        existing = await database.fetch_one(query, {"email": user_data.email})
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Validate password strength
        if len(user_data.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters"
            )
        
        # Hash password
        password_hash = hash_password(user_data.password)
        
        # Create user
        user_id = str(uuid.uuid4())
        query = """
            INSERT INTO users (id, email, password_hash, name, company_name, subscription_tier, subscription_status)
            VALUES (:id, :email, :password_hash, :name, :company_name, 'free', 'active')
            RETURNING id, email, name, company_name, subscription_tier, subscription_status, created_at
        """
        user = await database.fetch_one(
            query,
            {
                "id": user_id,
                "email": user_data.email,
                "password_hash": password_hash,
                "name": user_data.name,
                "company_name": user_data.company_name,
            }
        )
        
        # Create JWT token
        token = create_jwt_token(user_id, user_data.email, timedelta(hours=JWT_EXPIRY_HOURS))
        
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=JWT_EXPIRY_HOURS * 3600,
            user=UserResponse(
                id=user["id"],
                email=user["email"],
                name=user["name"],
                company_name=user["company_name"],
                subscription_tier=user["subscription_tier"],
                subscription_status=user["subscription_status"],
                created_at=user["created_at"]
            )
        )
    
    finally:
        await database.disconnect()

@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """
    Login with email and password
    
    Returns JWT token for authenticated requests
    """
    await database.connect()
    
    try:
        # Get user
        query = """
            SELECT id, email, password_hash, name, company_name, subscription_tier, subscription_status, created_at
            FROM users
            WHERE email = :email
        """
        user = await database.fetch_one(query, {"email": credentials.email})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Verify password
        if not verify_password(credentials.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Create JWT token
        token = create_jwt_token(str(user["id"]), user["email"], timedelta(hours=JWT_EXPIRY_HOURS))
        
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=JWT_EXPIRY_HOURS * 3600,
            user=UserResponse(
                id=str(user["id"]),
                email=user["email"],
                name=user["name"],
                company_name=user["company_name"],
                subscription_tier=user["subscription_tier"],
                subscription_status=user["subscription_status"],
                created_at=user["created_at"]
            )
        )
    
    finally:
        await database.disconnect()

@router.post("/verify", response_model=TokenVerify)
async def verify_token(token_data: Dict[str, str]):
    """Verify if a JWT token is valid"""
    payload = decode_jwt_token(token_data["token"])
    
    if not payload:
        return TokenVerify(valid=False, user=None, expires_at=None)
    
    # Get user info
    await database.connect()
    try:
        query = """
            SELECT id, email, name, company_name, subscription_tier, subscription_status, created_at
            FROM users
            WHERE id = :user_id
        """
        user = await database.fetch_one(query, {"user_id": payload["sub"]})
        
        if not user:
            return TokenVerify(valid=False, user=None, expires_at=None)
        
        return TokenVerify(
            valid=True,
            user=UserResponse(
                id=str(user["id"]),
                email=user["email"],
                name=user["name"],
                company_name=user["company_name"],
                subscription_tier=user["subscription_tier"],
                subscription_status=user["subscription_status"],
                created_at=user["created_at"]
            ),
            expires_at=datetime.fromtimestamp(payload["exp"])
        )
    finally:
        await database.disconnect()

@router.post("/password-reset/request")
async def request_password_reset(request_data: PasswordResetRequest):
    """
    Request a password reset token
    
    In production, this would send an email with a reset link
    For now, it just confirms the email exists
    """
    await database.connect()
    
    try:
        # Check if user exists
        query = "SELECT id FROM users WHERE email = :email"
        user = await database.fetch_one(query, {"email": request_data.email})
        
        if not user:
            # Don't reveal if email exists or not (security best practice)
            return {"message": "If the email exists, a reset link has been sent"}
        
        # Generate reset token
        reset_token = create_jwt_token(
            str(user["id"]), 
            request_data.email, 
            timedelta(hours=PASSWORD_RESET_EXPIRY_HOURS)
        )
        
        # TODO: Send email with reset link
        # For now, return token (ONLY FOR DEVELOPMENT!)
        return {
            "message": "Password reset token generated",
            "reset_token": reset_token,  # REMOVE IN PRODUCTION
            "note": "In production, this would be sent via email"
        }
    
    finally:
        await database.disconnect()

@router.post("/password-reset/confirm")
async def confirm_password_reset(reset_data: PasswordResetConfirm):
    """Confirm password reset with token"""
    await database.connect()
    
    try:
        # Verify reset token
        payload = decode_jwt_token(reset_data.token)
        
        if not payload or payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token"
            )
        
        # Validate new password
        if len(reset_data.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters"
            )
        
        # Hash new password
        password_hash = hash_password(reset_data.new_password)
        
        # Update password
        query = """
            UPDATE users
            SET password_hash = :password_hash, updated_at = CURRENT_TIMESTAMP
            WHERE id = :user_id
        """
        await database.execute(query, {
            "password_hash": password_hash,
            "user_id": payload["sub"]
        })
        
        return {"message": "Password reset successful"}
    
    finally:
        await database.disconnect()

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Get current user information"""
    await database.connect()
    
    try:
        query = """
            SELECT id, email, name, company_name, subscription_tier, subscription_status, created_at
            FROM users
            WHERE id = :user_id
        """
        user = await database.fetch_one(query, {"user_id": current_user["sub"]})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return UserResponse(
            id=str(user["id"]),
            email=user["email"],
            name=user["name"],
            company_name=user["company_name"],
            subscription_tier=user["subscription_tier"],
            subscription_status=user["subscription_status"],
            created_at=user["created_at"]
        )
    
    finally:
        await database.disconnect()

@router.put("/me", response_model=UserResponse)
async def update_user_profile(
    update_data: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Update user profile"""
    await database.connect()
    
    try:
        # Remove sensitive fields
        update_data.pop("password_hash", None)
        update_data.pop("subscription_tier", None)
        update_data.pop("subscription_status", None)
        
        # Build update query
        set_clauses = []
        values = {"user_id": current_user["sub"]}
        
        for key, value in update_data.items():
            if key in ["name", "company_name"]:
                set_clauses.append(f"{key} = :{key}")
                values[key] = value
        
        if not set_clauses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )
        
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        
        query = f"""
            UPDATE users
            SET {', '.join(set_clauses)}
            WHERE id = :user_id
            RETURNING id, email, name, company_name, subscription_tier, subscription_status, created_at
        """
        
        user = await database.fetch_one(query, values)
        
        return UserResponse(
            id=str(user["id"]),
            email=user["email"],
            name=user["name"],
            company_name=user["company_name"],
            subscription_tier=user["subscription_tier"],
            subscription_status=user["subscription_status"],
            created_at=user["created_at"]
        )
    
    finally:
        await database.disconnect()
