"""
QuikScore API - Company Health Intelligence
FastAPI Backend for UK Company Health Scoring
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/quikscore")

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

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - API info"""
    return {
        "service": "QuikScore API",
        "status": "running",
        "version": "0.1.0",
        "docs": "/docs"
    }

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

# Get company profile with health score
@app.get("/api/companies/{company_number}", response_model=CompanyProfile)
async def get_company_profile(company_number: str):
    """
    Get detailed company profile with AI health score
    """
    # Check cache
    cache_key = f"company:{company_number}"
    cached_result = await cache.get(cache_key)
    if cached_result:
        return json.loads(cached_result)
    
    # Fetch from Companies House
    async with httpx.AsyncClient() as client:
        # Get company profile
        profile_response = await client.get(
            f"https://api.company-information.service.gov.uk/company/{company_number}",
            auth=(COMPANIES_HOUSE_API_KEY, "")
        )
        
        if profile_response.status_code != 200:
            raise HTTPException(
                status_code=profile_response.status_code,
                detail="Company not found"
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


# Include auth router
app.include_router(auth_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
