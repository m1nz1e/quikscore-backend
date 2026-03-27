"""
QuikScore API - Company Health Intelligence
FastAPI Backend for UK Company Health Scoring
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import httpx
import os
import json
from datetime import datetime, timedelta
import redis.asyncio as redis
from databases import Database
from dotenv import load_dotenv
from health_scorer import QuikScoreEngine
from advanced_metrics import AdvancedMetricsEngine
from auth import router as auth_router

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Initialize FastAPI app
app = FastAPI(
    title="QuikScore API",
    description="AI-powered health scores for UK companies",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware - Allow specific origins (required for credentials)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://quik-score.vercel.app",
        "https://quikscore.vercel.app",
        "http://localhost:3000",  # Dev
        "http://192.168.0.129:3080"  # Nerve
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Configuration
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/quikscore")

# Authentication middleware - Extracts user info from JWT tokens
from middleware.auth_middleware import AuthMiddleware
app.add_middleware(AuthMiddleware)

# Rate limiting middleware - Per-user, tier-based limits
from middleware.rate_limiter import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware, redis_url=REDIS_URL)

# Request logger middleware - Logs all requests for security monitoring
from middleware.request_logger import RequestLoggerMiddleware
app.add_middleware(RequestLoggerMiddleware)

# Scraper blocker middleware - Blocks known automated scraping tools
from middleware.scraper_blocker import ScraperBlockerMiddleware
app.add_middleware(ScraperBlockerMiddleware)

# Initialize Redis cache
cache = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

# Initialize database
database = Database(DATABASE_URL)

# Health scoring weights
SCORING_WEIGHTS = {
    "status_dissolved": -100,
    "status_liquidation": -80,
    "status_administration": -60,
    "accounts_overdue": -40,
    "confirmation_overdue": -30,
    "accounts_soon_due": -20,
    "officer_turnover": -15,
    "new_company": -10,
    "established_company": +10,
    "consistent_filing": +10,
}

# Pydantic models
class CompanySearchRequest(BaseModel):
    query: str
    items_per_page: int = 20
    start_index: int = 0

class CompanyHealthScore(BaseModel):
    company_number: str
    company_name: str
    health_score: int
    score_band: str
    factors: List[Dict[str, Any]]
    recommendation: str
    calculated_at: datetime

class CompanyProfile(BaseModel):
    company_number: str
    company_name: str
    company_status: str
    company_type: Optional[str]
    incorporation_date: Optional[str]
    registered_office_address: Optional[Dict[str, str]]
    accounts: Optional[Dict[str, Any]]
    confirmation_statement: Optional[Dict[str, Any]]
    health_score: Optional[CompanyHealthScore]

# Lifespan events
@app.on_event("startup")
async def startup():
    """Initialize database connection"""
    await database.connect()
    print("[OK] QuikScore API started")

@app.on_event("shutdown")
async def shutdown():
    """Close database connection"""
    await database.disconnect()
    await cache.close()

# OPTIONS preflight handler for CORS
@app.options("/{path:path}")
async def options_handler(path: str, request: Request):
    """Handle CORS preflight requests"""
    return PlainTextResponse("OK")

# Health check endpoint
@app.get("/health")
async def health_check():
    """API health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0"
    }

# Company search endpoint (GET)
@app.get("/api/companies/search")
async def search_companies_get(query: str, items_per_page: int = 20, start_index: int = 0):
    """
    Search for UK companies by name or number (GET)
    """
    # Check cache first
    cache_key = f"search:{query}:{start_index}:{items_per_page}"
    cached_result = await cache.get(cache_key)
    if cached_result:
        return json.loads(cached_result)
    
    # Call Companies House API
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.company-information.service.gov.uk/search/companies",
            params={
                "q": query,
                "items_per_page": items_per_page,
                "start_index": start_index
            },
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail="Companies House API error"
            )
        
        result = response.json()
    
    # Cache for 1 hour
    await cache.setex(cache_key, 3600, json.dumps(result))
    
    return result

# Company search endpoint (POST)
@app.post("/api/companies/search")
async def search_companies_post(request: CompanySearchRequest):
    """
    Search for UK companies by name or number (POST)
    """
    # Delegate to GET endpoint for consistency
    return await search_companies_get(request.query, request.items_per_page, request.start_index)

# Get company profile with health score (with alias route for /api/company/{number})
@app.get("/api/companies/{company_number}", response_model=CompanyProfile)
@app.get("/api/company/{company_number}", response_model=CompanyProfile)  # Alias route
async def get_company_profile(company_number: str):
    """
    Get detailed company profile with AI health score
    Supports both /api/companies/{number} and /api/company/{number}
    """
    # Check cache
    cache_key = f"company:{company_number}"
    cached_result = await cache.get(cache_key)
    if cached_result:
        return json.loads(cached_result)
    
    # Fetch from Companies House
    async with httpx.AsyncClient() as client:
        # Get company profile
        try:
            profile_response = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}",
                auth=(COMPANIES_HOUSE_API_KEY, ""),
                timeout=10.0
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "api_timeout",
                    "message": "API unavailable — our servers are temporarily busy. Please try again in a few moments.",
                    "retry": True
                }
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "network_error",
                    "message": "Network error — check your connection and try again",
                    "retry": True
                }
            )
        
        if profile_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "company_not_found",
                    "message": "Company not found — please check the company number and try again. UK company numbers are typically 8 digits.",
                    "retry": False
                }
            )
        elif profile_response.status_code != 200:
            raise HTTPException(
                status_code=profile_response.status_code,
                detail={
                    "error": "companies_house_error",
                    "message": "Failed to fetch company data. Please try again later.",
                    "retry": True
                }
            )
        
        profile_data = profile_response.json()
    
    # Calculate health score
    health_score = calculate_health_score(profile_data)
    
    # Build response
    result = CompanyProfile(
        company_number=profile_data.get("company_number"),
        company_name=profile_data.get("company_name"),
        company_status=profile_data.get("company_status"),
        company_type=profile_data.get("company_type"),
        incorporation_date=profile_data.get("date_of_creation"),
        registered_office_address=profile_data.get("registered_office_address"),
        accounts=profile_data.get("accounts"),
        confirmation_statement=profile_data.get("confirmation_statement"),
        health_score=health_score
    )
    
    # Cache for 24 hours
    await cache.setex(cache_key, 86400, result.json())
    
    return result

# Health score calculation (rule-based MVP)
def calculate_health_score(company_data: Dict[str, Any]) -> CompanyHealthScore:
    """
    Calculate company health score using rule-based algorithm
    """
    score = 100
    factors = []
    
    # 1. Company Status (critical)
    status = company_data.get("company_status", "").lower()
    if status == "dissolved":
        score = 0
        factors.append({
            "factor": "status",
            "impact": -100,
            "message": "Company is dissolved"
        })
        return create_health_score_response(company_data, score, factors)
    
    elif status == "liquidation":
        score -= 80
        factors.append({
            "factor": "status",
            "impact": -80,
            "message": "Company in liquidation"
        })
    
    elif status == "administration":
        score -= 60
        factors.append({
            "factor": "status",
            "impact": -60,
            "message": "Company in administration"
        })
    
    # 2. Accounts Filing
    accounts = company_data.get("accounts", {})
    if accounts.get("overdue"):
        score -= 40
        factors.append({
            "factor": "accounts_overdue",
            "impact": -40,
            "message": "Accounts overdue"
        })
    
    # Check days until due
    next_due = accounts.get("next_due")
    if next_due:
        try:
            due_date = datetime.fromisoformat(next_due.replace("Z", "+00:00"))
            days_until_due = (due_date - datetime.now()).days
            
            if days_until_due < 7:
                score -= 20
                factors.append({
                    "factor": "accounts_very_soon_due",
                    "impact": -20,
                    "message": f"Accounts due in {days_until_due} days"
                })
            elif days_until_due < 30:
                score -= 10
                factors.append({
                    "factor": "accounts_soon_due",
                    "impact": -10,
                    "message": f"Accounts due in {days_until_due} days"
                })
        except:
            pass
    
    # 3. Confirmation Statement
    conf_stmt = company_data.get("confirmation_statement", {})
    if conf_stmt.get("overdue"):
        score -= 30
        factors.append({
            "factor": "confirmation_overdue",
            "impact": -30,
            "message": "Confirmation statement overdue"
        })
    
    # 4. Company Age
    incorporation_date = company_data.get("date_of_creation")
    if incorporation_date:
        try:
            inc_date = datetime.fromisoformat(incorporation_date.replace("Z", "+00:00"))
            age_years = (datetime.now() - inc_date).days / 365.25
            
            if age_years > 10:
                score += 10
                factors.append({
                    "factor": "established",
                    "impact": +10,
                    "message": "Well-established company (10+ years)"
                })
            elif age_years > 5:
                score += 5
                factors.append({
                    "factor": "mature",
                    "impact": +5,
                    "message": "Mature company (5+ years)"
                })
            elif age_years < 1:
                score -= 5
                factors.append({
                    "factor": "new",
                    "impact": -5,
                    "message": "Very new company (<1 year)"
                })
        except:
            pass
    
    # Clamp score to 0-100
    score = max(0, min(100, score))
    
    return create_health_score_response(company_data, score, factors)

def create_health_score_response(company_data: Dict[str, Any], score: int, factors: List[Dict]) -> CompanyHealthScore:
    """Create standardized health score response"""
    
    # Determine score band
    if score >= 90:
        band = "Excellent"
        recommendation = "Very low risk - company appears financially healthy"
    elif score >= 75:
        band = "Good"
        recommendation = "Low risk - company appears stable"
    elif score >= 60:
        band = "Fair"
        recommendation = "Moderate risk - monitor closely"
    elif score >= 40:
        band = "Poor"
        recommendation = "High risk - exercise caution"
    else:
        band = "Critical"
        recommendation = "Very high risk - avoid or monitor very closely"
    
    return CompanyHealthScore(
        company_number=company_data.get("company_number"),
        company_name=company_data.get("company_name"),
        health_score=score,
        score_band=band,
        factors=factors,
        recommendation=recommendation,
        calculated_at=datetime.utcnow()
    )

# Explainable health score endpoint (NEW - Full XAI)
@app.get("/api/companies/{company_number}/health-score-explainable")
async def get_explainable_health_score(company_number: str):
    """
    Get fully explainable company health score with complete breakdown.
    
    Every point is traceable to specific data sources.
    Perfect for compliance teams, audits, and customer explanations.
    
    Returns:
    - Total score (0-100)
    - Category breakdown (6 categories)
    - Every factor with evidence
    - Improvement recommendations
    - Data sources
    - Full audit trail
    """
    try:
        # Fetch company data from Companies House
        async with httpx.AsyncClient() as client:
            # Get company profile
            profile_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}",
                auth=(COMPANIES_HOUSE_API_KEY, "")
            )
            
            if profile_resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Company not found")
            elif profile_resp.status_code != 200:
                raise HTTPException(status_code=500, detail="Companies House API error")
            
            company_data = profile_resp.json()
            
            # Get additional data (filing history, officers, charges, etc.)
            # In production, these would be parallel requests
            filing_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}/filing-history",
                auth=(COMPANIES_HOUSE_API_KEY, ""),
                params={"items_per_page": 50}
            )
            if filing_resp.status_code == 200:
                company_data["filing_history"] = filing_resp.json()
            
            officers_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}/officers",
                auth=(COMPANIES_HOUSE_API_KEY, ""),
                params={"items_per_page": 50}
            )
            if officers_resp.status_code == 200:
                company_data["officers"] = officers_resp.json()
            
            charges_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}/charges",
                auth=(COMPANIES_HOUSE_API_KEY, "")
            )
            if charges_resp.status_code == 200:
                company_data["charges"] = charges_resp.json()
            
            # Get accounts data
            if company_data.get("accounts", {}).get("accounting_reference_date", {}):
                accounts_resp = await client.get(
                    f"https://api.company-information.service.gov.uk/company/{company_number}/accounts",
                    auth=(COMPANIES_HOUSE_API_KEY, "")
                )
                if accounts_resp.status_code == 200:
                    company_data["accounts"] = accounts_resp.json()
        
        # Calculate explainable health score
        engine = QuikScoreEngine()
        result = engine.calculate_health_score(
            company_number=company_number,
            company_name=company_data.get("company_name", "Unknown"),
            company_data=company_data
        )
        
        # Return as JSON
        return result.to_dict()
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating health score: {str(e)}")


# Bulk health scores endpoint (for Pro/Business tiers)
@app.post("/api/bulk/health-scores")
async def bulk_health_scores(company_numbers: List[str]):
    """
    Get health scores for multiple companies at once
    Available for Pro and Business tiers
    """
    results = []
    
    for company_number in company_numbers:
        try:
            # Fetch company data
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.company-information.service.gov.uk/company/{company_number}",
                    auth=(COMPANIES_HOUSE_API_KEY, "")
                )
                
                if response.status_code == 200:
                    profile_data = response.json()
                    health_score = calculate_health_score(profile_data)
                    results.append(health_score)
        except Exception as e:
            # Skip failed lookups
            continue
    
    return {"results": results, "count": len(results)}


# Advanced Metrics Endpoint (Phase 1 - NEW!)
@app.get("/api/companies/{company_number}/advanced-metrics")
async def get_advanced_metrics(company_number: str):
    """
    Get advanced predictive metrics using ONLY Companies House data.
    
    NEW METRICS (Phase 1):
    1. Filing Behavior Psychology - Predicts stress 3-6 months early
    2. Director Attention Index - Measures divided attention
    3. Capital Raise Desperation - Detects funding urgency
    4. QuikScore Confidence Index - How much to trust the score
    
    No additional API keys required!
    """
    try:
        # Fetch company data from Companies House
        async with httpx.AsyncClient() as client:
            # Get company profile
            profile_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}",
                auth=(COMPANIES_HOUSE_API_KEY, "")
            )
            
            if profile_resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Company not found")
            elif profile_resp.status_code != 200:
                raise HTTPException(status_code=500, detail="Companies House API error")
            
            company_data = profile_resp.json()
            
            # Get additional data
            filing_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}/filing-history",
                auth=(COMPANIES_HOUSE_API_KEY, ""),
                params={"items_per_page": 100}
            )
            if filing_resp.status_code == 200:
                company_data["filing_history"] = filing_resp.json()
            
            officers_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}/officers",
                auth=(COMPANIES_HOUSE_API_KEY, ""),
                params={"items_per_page": 50}
            )
            if officers_resp.status_code == 200:
                company_data["officers"] = officers_resp.json()
            
            charges_resp = await client.get(
                f"https://api.company-information.service.gov.uk/company/{company_number}/charges",
                auth=(COMPANIES_HOUSE_API_KEY, "")
            )
            if charges_resp.status_code == 200:
                company_data["charges"] = charges_resp.json()
        
        # Calculate advanced metrics
        engine = AdvancedMetricsEngine()
        metrics = engine.calculate_all_metrics(company_data)
        
        # Return as JSON
        return {
            "company_number": company_number,
            "company_name": company_data.get("company_name", "Unknown"),
            "calculated_at": datetime.now().isoformat(),
            "metrics": {
                metric_name: {
                    "score": result.score,
                    "max_score": result.max_score,
                    "rating": result.rating,
                    "risk_level": result.risk_level,
                    "factors": [asdict(f) for f in result.factors],
                    "insights": result.insights,
                    "recommendations": result.recommendations,
                    "data_sources": result.data_sources
                }
                for metric_name, result in metrics.items()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating metrics: {str(e)}")


# API usage endpoint
@app.get("/api/usage")
async def get_usage():
    """Get current API usage statistics"""
    return {
        "requests_today": 0,  # Implement tracking
        "requests_this_month": 0,
        "cache_hit_rate": 0.0,
        "average_response_time_ms": 0
    }


# Company Export Endpoint - CSV/JSON/PDF
@app.get("/api/company/{company_number}/export")
async def export_company_data(
    company_number: str,
    format: str = "json",  # json, csv, or pdf
    authorization: Optional[str] = Header(None)
):
    """
    Export company data in various formats.
    - FREE tier: Basic company info only
    - STARTER+: Extended data
    - PRO+: Full data including health score breakdown
    - BUSINESS: All data + ML predictions
    """
    from fastapi.responses import JSONResponse, Response
    
    # Verify auth (optional for FREE tier basic data)
    user_tier = "free"
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        try:
            # Verify token and get user tier
            async with httpx.AsyncClient() as client:
                verify_resp = await client.post(
                    f"{os.getenv('API_URL', 'http://localhost:8000')}/auth/verify",
                    json={"token": token}
                )
                if verify_resp.status_code == 200:
                    user_data = verify_resp.json()
                    user_tier = user_data.get("user", {}).get("subscription", {}).get("tier", "free")
        except Exception:
            pass  # Fall back to free tier
    
    # Fetch company data
    async with httpx.AsyncClient() as client:
        profile_response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if profile_response.status_code != 200:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "company_not_found",
                    "message": "Company not found. Please check the company number and try again.",
                    "retry": False
                }
            )
        
        company_data = profile_response.json()
    
    # Build export data based on tier
    export_data = {
        "company_number": company_data.get("company_number"),
        "company_name": company_data.get("company_name"),
        "company_status": company_data.get("company_status"),
        "company_type": company_data.get("company_type"),
        "incorporation_date": company_data.get("date_of_creation"),
        "registered_office_address": company_data.get("registered_office_address"),
        "exported_at": datetime.utcnow().isoformat(),
        "tier": user_tier,
    }
    
    # Add extended data for STARTER+
    if user_tier in ["starter", "pro", "business"]:
        export_data["accounts"] = company_data.get("accounts")
        export_data["confirmation_statement"] = company_data.get("confirmation_statement")
        export_data["sic_codes"] = company_data.get("sic_codes")
    
    # Add health score for PRO+
    if user_tier in ["pro", "business"]:
        health_score = calculate_health_score(company_data)
        export_data["health_score"] = health_score.dict()
    
    # Add ML predictions for BUSINESS
    if user_tier == "business":
        # Would call ML prediction endpoint here
        export_data["ml_predictions"] = {"note": "Available for BUSINESS tier"}
    
    # Return in requested format
    if format.lower() == "csv":
        # Simple CSV conversion (flat structure)
        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Flatten nested dicts for CSV
        def flatten(d, parent_key=''):
            items = []
            for k, v in d.items():
                new_key = f"{parent_key}.{k}" if parent_key else k
                if isinstance(v, dict):
                    items.extend(flatten(v, new_key).items())
                else:
                    items.append((new_key, v))
            return dict(items)
        
        flat_data = flatten(export_data)
        writer.writerow(flat_data.keys())
        writer.writerow(flat_data.values())
        
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={company_number}_export.csv"
            }
        )
    
    elif format.lower() == "pdf":
        # PDF generation would require a library like reportlab or weasyprint
        # For now, return JSON with note
        raise HTTPException(
            status_code=501,
            detail={
                "error": "pdf_not_implemented",
                "message": "PDF export is coming soon. Please use JSON or CSV format.",
                "alternative_formats": ["json", "csv"]
            }
        )
    
    else:  # JSON (default)
        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": f"attachment; filename={company_number}_export.json"
            }
        )


# ============================================================================
# MISSING ENDPOINTS - Added to fix 405 errors (BUG-002)
# These endpoints return proper responses instead of 405 Method Not Allowed
# ============================================================================

# Health Score Endpoint
@app.get("/api/company/{company_number}/health")
async def get_company_health(company_number: str):
    """
    Get company health score.
    Returns health score data for the specified company.
    """
    async with httpx.AsyncClient() as client:
        profile_response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if profile_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail={"error": "company_not_found", "message": "Company not found"}
            )
        elif profile_response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail={"error": "companies_house_error", "message": "Failed to fetch company data"}
            )
        
        company_data = profile_response.json()
        health_score = calculate_health_score(company_data)
        
        return {
            "company_number": company_number,
            "company_name": company_data.get("company_name"),
            "health_score": health_score.health_score,
            "score_band": health_score.score_band,
            "rating": health_score.score_band,
            "color": "green" if health_score.health_score >= 75 else "yellow" if health_score.health_score >= 50 else "red",
            "factors": [f.dict() for f in health_score.factors],
            "recommendation": health_score.recommendation,
            "calculated_at": health_score.calculated_at.isoformat()
        }


# Accounts Data Endpoint
@app.get("/api/company/{company_number}/accounts")
async def get_company_accounts(company_number: str):
    """
    Get company accounts data from Companies House.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}/accounts",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail={"error": "company_not_found", "message": "Company not found"})
        elif response.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "companies_house_error", "message": "Failed to fetch accounts"})
        
        accounts_data = response.json()
        return {
            "company_number": company_number,
            "accounts": accounts_data,
            "tier": "free"
        }


# Insolvency Data Endpoint
@app.get("/api/company/{company_number}/insolvency")
async def get_company_insolvency(company_number: str):
    """
    Get company insolvency data from Companies House.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}/insolvency",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail={"error": "company_not_found", "message": "Company not found"})
        elif response.status_code != 200:
            # Insolvency endpoint may return 404 if no insolvency data exists
            return {
                "company_number": company_number,
                "insolvency_records": [],
                "has_insolvency": False,
                "tier": "free"
            }
        
        insolvency_data = response.json()
        return {
            "company_number": company_number,
            "insolvency_records": insolvency_data.get("items", []),
            "has_insolvency": len(insolvency_data.get("items", [])) > 0,
            "total_count": insolvency_data.get("total_count", 0),
            "tier": "free"
        }


# Land Registry Data Endpoint (Not Implemented - External API Required)
@app.get("/api/company/{company_number}/land-registry")
async def get_land_registry_data(company_number: str):
    """
    Get property/land registry data for the company.
    Note: Requires HM Land Registry API integration (planned for Business tier).
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error": "not_implemented",
            "message": "Land registry data requires HM Land Registry API integration. Available for Business tier in Q2 2026.",
            "planned_tier": "business",
            "planned_release": "Q2 2026"
        }
    )


# EPC (Energy Performance Certificate) Data Endpoint
@app.get("/api/company/{company_number}/epc")
async def get_epc_data(company_number: str):
    """
    Get EPC (Energy Performance Certificate) data for company properties.
    Note: Requires integration with EPC register (planned).
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error": "not_implemented",
            "message": "EPC data integration is planned. This will provide energy efficiency ratings for company properties.",
            "planned_tier": "pro",
            "planned_release": "Q2 2026"
        }
    )


# CCJ (County Court Judgment) Data Endpoint
@app.get("/api/company/{company_number}/ccj")
async def get_ccj_data(company_number: str):
    """
    Get CCJ (County Court Judgment) data for the company.
    Note: Requires Registry Trust API integration (planned for Pro/Business tier).
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error": "not_implemented",
            "message": "CCJ data requires Registry Trust API integration. Available for Pro/Business tier in Q2 2026.",
            "planned_tier": "pro",
            "planned_release": "Q2 2026"
        }
    )


# FCA (Financial Conduct Authority) Data Endpoint
@app.get("/api/company/{company_number}/fca")
async def get_fca_data(company_number: str):
    """
    Get FCA registration and regulatory data for the company.
    Note: Requires FCA API integration (planned for Business tier).
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error": "not_implemented",
            "message": "FCA regulatory data requires FCA API integration. Available for Business tier in Q2 2026.",
            "planned_tier": "business",
            "planned_release": "Q2 2026"
        }
    )


# Officer Network Endpoint
@app.get("/api/company/{company_number}/officer-network")
async def get_officer_network(company_number: str):
    """
    Get officer network analysis - shows connections between directors across companies.
    Uses director attention score data.
    """
    async with httpx.AsyncClient() as client:
        # Get officers list
        officers_response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}/officers",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if officers_response.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "companies_house_error", "message": "Failed to fetch officers"})
        
        officers_data = officers_response.json()
        officers = officers_data.get("items", [])
        
        # Build officer network (simplified - in production would cross-reference all appointments)
        officer_network = []
        for officer in officers:
            if officer.get("officer_role") == "director":
                officer_network.append({
                    "name": officer.get("name"),
                    "officer_role": officer.get("officer_role"),
                    "appointed_on": officer.get("appointed_on"),
                    "resigned_on": officer.get("resigned_on"),
                    "attention_score": officer.get("attention_score", {}),
                    "other_appointments": "Available in Pro tier"  # Would fetch from cross-reference
                })
        
        return {
            "company_number": company_number,
            "officer_network": officer_network,
            "total_officers": len(officers),
            "active_directors": len([o for o in officers if o.get("officer_role") == "director" and not o.get("resigned_on")]),
            "tier": "free"
        }


# Similar Companies Endpoint
@app.get("/api/company/{company_number}/similar")
async def get_similar_companies(company_number: str):
    """
    Get similar companies based on SIC codes, size, and industry.
    Uses Companies House data to find comparable companies.
    """
    async with httpx.AsyncClient() as client:
        # Get company profile for SIC codes
        profile_response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if profile_response.status_code != 200:
            raise HTTPException(status_code=404, detail={"error": "company_not_found", "message": "Company not found"})
        
        company_data = profile_response.json()
        sic_codes = company_data.get("sic_codes", [])
        
        # Search for similar companies by SIC code (simplified)
        if sic_codes:
            search_response = await client.get(
                "https://api.company-information.service.gov.uk/search/companies",
                params={"q": sic_codes[0], "items_per_page": 5},
                auth=(COMPANIES_HOUSE_API_KEY, "")
            )
            
            if search_response.status_code == 200:
                search_results = search_response.json()
                similar = [
                    {
                        "company_number": c.get("company_number"),
                        "company_name": c.get("title"),
                        "company_status": c.get("company_status"),
                        "similarity_reason": "Same SIC code"
                    }
                    for c in search_results.get("items", [])[:5]
                    if c.get("company_number") != company_number
                ]
            else:
                similar = []
        else:
            similar = []
        
        return {
            "company_number": company_number,
            "similar_companies": similar,
            "based_on": {"sic_codes": sic_codes},
            "tier": "free"
        }


# Trends Data Endpoint
@app.get("/api/company/{company_number}/trends")
async def get_company_trends(company_number: str):
    """
    Get company trends analysis - filing patterns, health score history.
    Note: Full trends require historical data storage (planned for Pro tier).
    """
    async with httpx.AsyncClient() as client:
        # Get filing history for trend analysis
        filing_response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}/filing-history",
            auth=(COMPANIES_HOUSE_API_KEY, ""),
            params={"items_per_page": 50}
        )
        
        if filing_response.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "companies_house_error", "message": "Failed to fetch filing history"})
        
        filing_data = filing_response.json()
        items = filing_data.get("items", [])
        
        # Analyze filing patterns (simplified)
        filing_types = {}
        for item in items:
            category = item.get("category", "unknown")
            filing_types[category] = filing_types.get(category, 0) + 1
        
        return {
            "company_number": company_number,
            "filing_trends": {
                "total_filings": len(items),
                "by_category": filing_types,
                "recent_filing_count": len([i for i in items if i.get("date") and i["date"] > "2025-01-01"])
            },
            "health_score_trend": "Historical trends available in Pro tier",
            "tier": "free"
        }


# Filing History Endpoint
@app.get("/api/company/{company_number}/filing-history")
async def get_filing_history(company_number: str, items_per_page: int = 25):
    """
    Get company filing history from Companies House.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}/filing-history",
            auth=(COMPANIES_HOUSE_API_KEY, ""),
            params={"items_per_page": items_per_page}
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail={"error": "company_not_found", "message": "Company not found"})
        elif response.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "companies_house_error", "message": "Failed to fetch filing history"})
        
        filing_data = response.json()
        return {
            "company_number": company_number,
            "filing_history": filing_data.get("items", []),
            "total_count": filing_data.get("total_count", 0),
            "start_index": filing_data.get("start_index", 0),
            "tier": "free"
        }


# Persons with Significant Control (PSC) Endpoint
@app.get("/api/company/{company_number}/persons-with-significant-control")
async def get_psc_data(company_number: str):
    """
    Get Persons with Significant Control (PSC) data from Companies House.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}/persons-with-significant-control",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail={"error": "company_not_found", "message": "Company not found"})
        elif response.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "companies_house_error", "message": "Failed to fetch PSC data"})
        
        psd_data = response.json()
        return {
            "company_number": company_number,
            "persons_with_significant_control": psd_data.get("items", []),
            "total_count": psd_data.get("total_count", 0),
            "tier": "free"
        }


# User Profile Endpoint
@app.get("/api/user/profile")
async def get_user_profile(authorization: Optional[str] = Header(None)):
    """
    Get current user profile. Requires authentication.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Authentication required. Please provide a valid JWT token."}
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        async with httpx.AsyncClient() as client:
            verify_resp = await client.post(
                f"{os.getenv('API_URL', 'http://localhost:8000')}/auth/verify",
                json={"token": token}
            )
            
            if verify_resp.status_code != 200 or not verify_resp.json().get("valid"):
                raise HTTPException(
                    status_code=401,
                    detail={"error": "invalid_token", "message": "Invalid or expired token"}
                )
            
            user_data = verify_resp.json().get("user", {})
            return {
                "user": user_data,
                "tier": user_data.get("subscription_tier", "free")
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "auth_service_error", "message": "Authentication service unavailable"})


# User Subscription Endpoint
@app.get("/api/user/subscription")
async def get_user_subscription(authorization: Optional[str] = Header(None)):
    """
    Get current user subscription details. Requires authentication.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Authentication required. Please provide a valid JWT token."}
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        async with httpx.AsyncClient() as client:
            verify_resp = await client.post(
                f"{os.getenv('API_URL', 'http://localhost:8000')}/auth/verify",
                json={"token": token}
            )
            
            if verify_resp.status_code != 200 or not verify_resp.json().get("valid"):
                raise HTTPException(
                    status_code=401,
                    detail={"error": "invalid_token", "message": "Invalid or expired token"}
                )
            
            user_data = verify_resp.json().get("user", {})
            return {
                "subscription": {
                    "tier": user_data.get("subscription_tier", "free"),
                    "status": user_data.get("subscription_status", "inactive"),
                    "features": get_tier_features(user_data.get("subscription_tier", "free"))
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "auth_service_error", "message": "Authentication service unavailable"})


def get_tier_features(tier: str) -> List[str]:
    """Return feature list for subscription tier"""
    features = {
        "free": ["Basic company lookup", "Health score", "5 searches/day"],
        "starter": ["Extended data", "Export (CSV/JSON)", "50 searches/day"],
        "pro": ["Advanced metrics", "Bulk lookups", "Officer network", "Unlimited searches"],
        "business": ["ML predictions", "API access", "Land registry data", "Priority support"]
    }
    return features.get(tier, features["free"])


# Include auth router
app.include_router(auth_router)

# Include honeypot endpoints (trap endpoints for scraper detection)
from endpoints_honeypot import router as honeypot_router
app.include_router(honeypot_router)

# Include admin endpoints (security monitoring)
from admin import router as admin_router
app.include_router(admin_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
