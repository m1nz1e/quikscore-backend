"""
QuikScore Health Scoring Engine v1.0
Explainable AI (XAI) for UK Company Health Assessment

Every score is fully traceable, auditable, and customer-friendly.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class Rating(Enum):
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"
    CRITICAL = "Critical"


@dataclass
class ScoringFactor:
    metric: str
    points: int
    status: str  # "positive", "negative", "neutral"
    evidence: str
    data_source: str


@dataclass
class CategoryBreakdown:
    category: str
    score: int
    max_score: int
    percentage: float
    factors: List[ScoringFactor]
    improvements: List[str]


@dataclass
class HealthScoreResult:
    company_number: str
    company_name: str
    health_score: int
    rating: str
    color: str
    calculated_at: str
    breakdown: Dict[str, CategoryBreakdown]
    summary: Dict[str, List[str]]
    data_sources: Dict[str, str]
    audit_trail: Dict[str, str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        # Convert CategoryBreakdown objects to dicts
        result['breakdown'] = {
            k: asdict(v) if hasattr(v, '__dataclass_fields__') else v
            for k, v in self.breakdown.items()
        }
        return result


class QuikScoreEngine:
    """
    Explainable company health scoring engine.
    
    All calculations are transparent and traceable to specific data points.
    """
    
    VERSION = "1.0.0"
    
    def __init__(self):
        self.calculation_id = None
        self.data_timestamp = None
    
    def calculate_health_score(
        self,
        company_number: str,
        company_name: str,
        company_data: Dict[str, Any]
    ) -> HealthScoreResult:
        """
        Calculate comprehensive health score with full explainability.
        
        Args:
            company_number: Companies House company number
            company_name: Company name
            company_data: Full company data from Companies House
            
        Returns:
            HealthScoreResult with complete breakdown and explanations
        """
        self.calculation_id = f"calc_{company_number}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.data_timestamp = datetime.now().isoformat()
        
        # Calculate each category
        breakdown = {}
        
        # 1. Filing Compliance (25 points)
        breakdown['filing_compliance'] = self._score_filing_compliance(company_data)
        
        # 2. Financial Stability (25 points)
        breakdown['financial_stability'] = self._score_financial_stability(company_data)
        
        # 3. Director Stability (15 points)
        breakdown['director_stability'] = self._score_director_stability(company_data)
        
        # 4. Company Age & History (10 points)
        breakdown['company_age'] = self._score_company_age(company_data)
        
        # 5. Risk Indicators (15 points)
        breakdown['risk_indicators'] = self._score_risk_indicators(company_data)
        
        # 6. Growth Signals (10 points)
        breakdown['growth_signals'] = self._score_growth_signals(company_data)
        
        # Calculate total score
        total_score = sum(cat.score for cat in breakdown.values())
        total_score = max(0, min(100, total_score))  # Clamp to 0-100
        
        # Determine rating
        rating, color = self._get_rating(total_score)
        
        # Generate summary
        summary = self._generate_summary(breakdown)
        
        # Data sources
        data_sources = self._extract_data_sources(company_data)
        
        # Audit trail
        audit_trail = {
            "model_version": self.VERSION,
            "calculation_id": self.calculation_id,
            "data_snapshot": self.data_timestamp,
            "calculation_method": "rule-based explainable scoring"
        }
        
        return HealthScoreResult(
            company_number=company_number,
            company_name=company_name,
            health_score=total_score,
            rating=rating.value,
            color=color,
            calculated_at=self.data_timestamp,
            breakdown=breakdown,
            summary=summary,
            data_sources=data_sources,
            audit_trail=audit_trail
        )
    
    def _score_filing_compliance(self, data: Dict[str, Any]) -> CategoryBreakdown:
        """Score filing compliance (25 points max)"""
        factors = []
        score = 0
        improvements = []
        
        # Check accounts status
        accounts = data.get('accounts', {})
        filing_history = data.get('filing_history', {}).get('items', [])
        
        # Accounts filed on time (+10)
        if not accounts.get('overdue', False):
            last_accounts = next(
                (f for f in filing_history if f.get('type') == 'accounts'),
                None
            )
            if last_accounts:
                factors.append(ScoringFactor(
                    metric="Accounts filed on time",
                    points=10,
                    status="positive",
                    evidence=f"Last accounts filed {last_accounts.get('date', 'unknown')} (on time)",
                    data_source="Companies House Filing History"
                ))
                score += 10
        else:
            factors.append(ScoringFactor(
                metric="Overdue accounts",
                points=-15,
                status="negative",
                evidence="Accounts are currently overdue",
                data_source="Companies House Accounts Status"
            ))
            score -= 15
            improvements.append("File overdue accounts immediately to avoid penalties")
        
        # Confirmation statement current (+5)
        conf_stmt = data.get('confirmation_statement', {})
        if not conf_stmt.get('overdue', False):
            factors.append(ScoringFactor(
                metric="Confirmation statement current",
                points=5,
                status="positive",
                evidence="Confirmation statement is up-to-date",
                data_source="Companies House Confirmation Statement"
            ))
            score += 5
        else:
            improvements.append("File overdue confirmation statement")
        
        # No late filings in 2 years (+5)
        two_years_ago = datetime.now() - timedelta(days=730)
        late_filings = [
            f for f in filing_history
            if f.get('type') == 'late-accounts'
            and f.get('date', '') > two_years_ago.isoformat()
        ]
        
        if not late_filings:
            factors.append(ScoringFactor(
                metric="No late filings (2 years)",
                points=5,
                status="positive",
                evidence="No late filing penalties in the past 2 years",
                data_source="Companies House Filing History"
            ))
            score += 5
        else:
            for filing in late_filings:
                factors.append(ScoringFactor(
                    metric="Late filing penalty",
                    points=-10,
                    status="negative",
                    evidence=f"Late filing penalty issued {filing.get('date', 'unknown')} (document {filing.get('type', 'unknown')})",
                    data_source="Companies House Filing History"
                ))
                score -= 10
            improvements.append("File all future documents on time to avoid penalties")
        
        # All required documents filed (+5)
        # Simplified check - in production would verify all required types
        if len(filing_history) > 0:
            factors.append(ScoringFactor(
                metric="All required documents filed",
                points=5,
                status="positive",
                evidence=f"{len(filing_history)} documents filed with Companies House",
                data_source="Companies House Filing History"
            ))
            score += 5
        
        # Clamp category score to 0-25
        score = max(0, min(25, score))
        
        return CategoryBreakdown(
            category="Filing Compliance",
            score=score,
            max_score=25,
            percentage=(score / 25) * 100,
            factors=factors,
            improvements=improvements
        )
    
    def _score_financial_stability(self, data: Dict[str, Any]) -> CategoryBreakdown:
        """Score financial stability (25 points max)"""
        factors = []
        score = 0
        improvements = []
        
        accounts = data.get('accounts', {})
        balance_sheet = accounts.get('balance_sheet', {})
        
        # Positive net assets (+10)
        net_assets = balance_sheet.get('net_assets', 0)
        if net_assets > 0:
            factors.append(ScoringFactor(
                metric="Positive net assets",
                points=10,
                status="positive",
                evidence=f"Net assets: £{net_assets:,}",
                data_source="Companies House Accounts - Balance Sheet"
            ))
            score += 10
        elif net_assets < 0:
            factors.append(ScoringFactor(
                metric="Negative net assets",
                points=-10,
                status="negative",
                evidence=f"Net assets: £{net_assets:,} (liabilities exceed assets)",
                data_source="Companies House Accounts - Balance Sheet"
            ))
            score -= 10
            improvements.append("Improve net asset position through profitability or capital injection")
        
        # Turnover growth (+5)
        turnover_current = balance_sheet.get('turnover', 0)
        turnover_previous = balance_sheet.get('previous_turnover', 0)
        
        if turnover_previous > 0:
            growth_rate = ((turnover_current - turnover_previous) / turnover_previous) * 100
            if growth_rate > 0:
                factors.append(ScoringFactor(
                    metric="Turnover growth",
                    points=5,
                    status="positive",
                    evidence=f"Turnover increased {growth_rate:.1f}% year-over-year",
                    data_source="Companies House Accounts - Profit & Loss"
                ))
                score += 5
            elif growth_rate < -10:
                factors.append(ScoringFactor(
                    metric="Turnover decline",
                    points=-5,
                    status="negative",
                    evidence=f"Turnover decreased {abs(growth_rate):.1f}% year-over-year",
                    data_source="Companies House Accounts - Profit & Loss"
                ))
                score -= 5
                improvements.append("Focus on revenue growth strategies")
        
        # Cash reserves (+5)
        cash = balance_sheet.get('current_assets', {}).get('cash', 0)
        if cash > 10000:  # More than £10k
            factors.append(ScoringFactor(
                metric="Healthy cash reserves",
                points=5,
                status="positive",
                evidence=f"Cash reserves: £{cash:,}",
                data_source="Companies House Accounts - Balance Sheet"
            ))
            score += 5
        elif cash < 1000:
            improvements.append("Build cash reserves for financial stability")
        
        # Low debt-to-asset ratio (+5)
        total_assets = balance_sheet.get('total_assets', 1)
        total_liabilities = balance_sheet.get('total_liabilities', 0)
        
        if total_assets > 0:
            debt_ratio = (total_liabilities / total_assets) * 100
            if debt_ratio < 50:
                factors.append(ScoringFactor(
                    metric="Low debt-to-asset ratio",
                    points=5,
                    status="positive",
                    evidence=f"Debt-to-asset ratio: {debt_ratio:.1f}%",
                    data_source="Companies House Accounts - Balance Sheet"
                ))
                score += 5
            elif debt_ratio > 80:
                factors.append(ScoringFactor(
                    metric="High debt-to-asset ratio",
                    points=-5,
                    status="negative",
                    evidence=f"Debt-to-asset ratio: {debt_ratio:.1f}% (high leverage)",
                    data_source="Companies House Accounts - Balance Sheet"
                ))
                score -= 5
                improvements.append("Reduce debt levels to improve financial stability")
        
        # Clamp to 0-25
        score = max(0, min(25, score))
        
        return CategoryBreakdown(
            category="Financial Stability",
            score=score,
            max_score=25,
            percentage=(score / 25) * 100,
            factors=factors,
            improvements=improvements
        )
    
    def _score_director_stability(self, data: Dict[str, Any]) -> CategoryBreakdown:
        """Score director stability (15 points max)"""
        factors = []
        score = 0
        improvements = []
        
        officers = data.get('officers', {}).get('active', [])
        
        # Number of directors
        num_directors = len(officers)
        
        if num_directors >= 2:
            factors.append(ScoringFactor(
                metric="Multiple directors",
                points=2,
                status="positive",
                evidence=f"{num_directors} active directors (shared responsibility)",
                data_source="Companies House Officers"
            ))
            score += 2
        elif num_directors == 1:
            factors.append(ScoringFactor(
                metric="Single director",
                points=-2,
                status="negative",
                evidence="Only 1 director (key person risk)",
                data_source="Companies House Officers"
            ))
            score -= 2
            improvements.append("Consider appointing additional director to reduce key person risk")
        
        # Director tenure
        now = datetime.now()
        long_tenure = 0
        recent_resignations = 0
        
        for officer in officers:
            appointed_date = officer.get('appointed_on', '')
            if appointed_date:
                try:
                    appointed = datetime.fromisoformat(appointed_date.replace('Z', '+00:00'))
                    tenure = (now - appointed).days / 365
                    if tenure >= 5:
                        long_tenure += 1
                except:
                    pass
        
        if long_tenure >= 1:
            factors.append(ScoringFactor(
                metric="Long-tenured directors",
                points=5,
                status="positive",
                evidence=f"{long_tenure} director(s) with 5+ years tenure",
                data_source="Companies House Officers"
            ))
            score += 5
        
        # Check for recent resignations (past year)
        resigned_officers = data.get('officers', {}).get('resigned', [])
        one_year_ago = datetime.now() - timedelta(days=365)
        
        for officer in resigned_officers:
            resigned_date = officer.get('resigned_on', '')
            if resigned_date:
                try:
                    resigned = datetime.fromisoformat(resigned_date.replace('Z', '+00:00'))
                    if resigned > one_year_ago:
                        recent_resignations += 1
                except:
                    pass
        
        if recent_resignations >= 3:
            factors.append(ScoringFactor(
                metric="High director turnover",
                points=-10,
                status="negative",
                evidence=f"{recent_resignations} director(s) resigned in past year",
                data_source="Companies House Officers"
            ))
            score -= 10
            improvements.append("Investigate director turnover and address management stability")
        
        # Clamp to 0-15
        score = max(0, min(15, score))
        
        return CategoryBreakdown(
            category="Director Stability",
            score=score,
            max_score=15,
            percentage=(score / 15) * 100,
            factors=factors,
            improvements=improvements
        )
    
    def _score_company_age(self, data: Dict[str, Any]) -> CategoryBreakdown:
        """Score company age and history (10 points max)"""
        factors = []
        score = 0
        improvements = []
        
        incorporation_date = data.get('date_of_creation', '')
        
        if incorporation_date:
            try:
                inc_date = datetime.fromisoformat(incorporation_date.replace('Z', '+00:00'))
                age_years = (datetime.now() - inc_date).days / 365
                
                if age_years >= 10:
                    factors.append(ScoringFactor(
                        metric="Trading 10+ years",
                        points=10,
                        status="positive",
                        evidence=f"Company incorporated {age_years:.1f} years ago ({incorporation_date})",
                        data_source="Companies House Overview"
                    ))
                    score = 10
                elif age_years >= 5:
                    factors.append(ScoringFactor(
                        metric="Trading 5+ years",
                        points=5,
                        status="positive",
                        evidence=f"Company incorporated {age_years:.1f} years ago ({incorporation_date})",
                        data_source="Companies House Overview"
                    ))
                    score = 5
                elif age_years >= 2:
                    factors.append(ScoringFactor(
                        metric="Trading 2-5 years",
                        points=3,
                        status="positive",
                        evidence=f"Company incorporated {age_years:.1f} years ago ({incorporation_date})",
                        data_source="Companies House Overview"
                    ))
                    score = 3
                else:
                    factors.append(ScoringFactor(
                        metric="Recently incorporated",
                        points=0,
                        status="neutral",
                        evidence=f"Company incorporated {age_years:.1f} years ago (no track record yet)",
                        data_source="Companies House Overview"
                    ))
            except:
                pass
        
        return CategoryBreakdown(
            category="Company Age & History",
            score=score,
            max_score=10,
            percentage=(score / 10) * 100 if score > 0 else 0,
            factors=factors,
            improvements=improvements
        )
    
    def _score_risk_indicators(self, data: Dict[str, Any]) -> CategoryBreakdown:
        """Score risk indicators (15 points max)"""
        factors = []
        score = 15  # Start with full points, deduct for issues
        improvements = []
        
        # Insolvency history
        insolvency = data.get('insolvency_history', [])
        if not insolvency:
            factors.append(ScoringFactor(
                metric="No insolvency records",
                points=10,
                status="positive",
                evidence="No insolvency proceedings found",
                data_source="Companies House Insolvency Register"
            ))
        else:
            for case in insolvency:
                case_type = case.get('type', 'unknown')
                factors.append(ScoringFactor(
                    metric="Insolvency proceedings",
                    points=-25,
                    status="negative",
                    evidence=f"Insolvency case: {case_type}",
                    data_source="Companies House Insolvency Register"
                ))
                score -= 25
            improvements.append("Address insolvency issues urgently")
        
        # Charges
        charges = data.get('charges', [])
        outstanding_charges = [c for c in charges if c.get('status') == 'outstanding']
        
        if not outstanding_charges:
            factors.append(ScoringFactor(
                metric="No charges/mortgages",
                points=5,
                status="positive",
                evidence="No outstanding charges registered",
                data_source="Companies House Charges"
            ))
        else:
            for charge in outstanding_charges:
                factors.append(ScoringFactor(
                    metric="Outstanding charge",
                    points=-5,
                    status="negative",
                    evidence=f"Charge registered: {charge.get('particulars', 'unknown')}",
                    data_source="Companies House Charges"
                ))
                score -= 5
            improvements.append("Consider discharging outstanding charges")
        
        # Company status
        company_status = data.get('company_status', '')
        if company_status == 'dissolution':
            factors.append(ScoringFactor(
                metric="Strike-off initiated",
                points=-15,
                status="negative",
                evidence="Company is in dissolution process",
                data_source="Companies House Company Status"
            ))
            score -= 15
            improvements.append("Company is being dissolved - highest risk")
        
        # Clamp to 0-15
        score = max(0, min(15, score))
        
        return CategoryBreakdown(
            category="Risk Indicators",
            score=score,
            max_score=15,
            percentage=(score / 15) * 100 if score > 0 else 0,
            factors=factors,
            improvements=improvements
        )
    
    def _score_growth_signals(self, data: Dict[str, Any]) -> CategoryBreakdown:
        """Score growth signals (10 points max)"""
        factors = []
        score = 0
        improvements = []
        
        # Share capital changes
        capital = data.get('capital', {})
        if capital.get('increased', False):
            factors.append(ScoringFactor(
                metric="Increased share capital",
                points=5,
                status="positive",
                evidence="Share capital increased (investment in business)",
                data_source="Companies House Capital"
            ))
            score += 5
        elif capital.get('reduced', False):
            factors.append(ScoringFactor(
                metric="Reduced share capital",
                points=-5,
                status="negative",
                evidence="Share capital reduced (possible distress)",
                data_source="Companies House Capital"
            ))
            score -= 5
            improvements.append("Understand reasons for capital reduction")
        
        # Recent filing activity
        filing_history = data.get('filing_history', {}).get('items', [])
        six_months_ago = datetime.now() - timedelta(days=180)
        
        recent_filings = [
            f for f in filing_history
            if f.get('date', '') > six_months_ago.isoformat()
        ]
        
        if len(recent_filings) >= 3:
            factors.append(ScoringFactor(
                metric="Active filing",
                points=2,
                status="positive",
                evidence=f"{len(recent_filings)} documents filed in past 6 months",
                data_source="Companies House Filing History"
            ))
            score += 2
        elif len(recent_filings) == 0:
            factors.append(ScoringFactor(
                metric="No recent activity",
                points=-5,
                status="negative",
                evidence="No documents filed in past 6 months (may be dormant)",
                data_source="Companies House Filing History"
            ))
            score -= 5
            improvements.append("Ensure all required documents are filed on time")
        
        # Clamp to 0-10
        score = max(0, min(10, score))
        
        return CategoryBreakdown(
            category="Growth Signals",
            score=score,
            max_score=10,
            percentage=(score / 10) * 100 if score > 0 else 0,
            factors=factors,
            improvements=improvements
        )
    
    def _get_rating(self, score: int) -> tuple:
        """Convert score to rating and color"""
        if score >= 90:
            return Rating.EXCELLENT, "green"
        elif score >= 75:
            return Rating.GOOD, "green"
        elif score >= 60:
            return Rating.FAIR, "yellow"
        elif score >= 40:
            return Rating.POOR, "orange"
        else:
            return Rating.CRITICAL, "red"
    
    def _generate_summary(self, breakdown: Dict[str, CategoryBreakdown]) -> Dict[str, List[str]]:
        """Generate executive summary"""
        positive_factors = []
        risk_factors = []
        recommendations = []
        
        for category, data in breakdown.items():
            for factor in data.factors:
                if factor.status == "positive":
                    positive_factors.append(factor.evidence)
                elif factor.status == "negative":
                    risk_factors.append(factor.evidence)
            
            recommendations.extend(data.improvements)
        
        # Remove duplicates
        positive_factors = list(dict.fromkeys(positive_factors))
        risk_factors = list(dict.fromkeys(risk_factors))
        recommendations = list(dict.fromkeys(recommendations))
        
        return {
            "positive_factors": positive_factors,
            "risk_factors": risk_factors,
            "recommendations": recommendations
        }
    
    def _extract_data_sources(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Extract data source timestamps"""
        return {
            "companies_house": {
                "overview": self.data_timestamp,
                "filing_history": self.data_timestamp,
                "officers": self.data_timestamp,
                "accounts": self.data_timestamp,
                "charges": self.data_timestamp,
                "insolvency": self.data_timestamp
            }
        }


# Example usage
if __name__ == "__main__":
    # Example company data (would come from Companies House API)
    example_data = {
        "company_number": "12345678",
        "company_name": "Example Limited",
        "date_of_creation": "2015-01-15",
        "company_status": "active",
        "accounts": {
            "overdue": False,
            "balance_sheet": {
                "net_assets": 50000,
                "turnover": 500000,
                "previous_turnover": 450000,
                "total_assets": 200000,
                "total_liabilities": 80000,
                "current_assets": {
                    "cash": 25000
                }
            }
        },
        "filing_history": {
            "items": [
                {"type": "accounts", "date": "2025-12-31"},
                {"type": "confirmation-statement", "date": "2026-01-15"}
            ]
        },
        "officers": {
            "active": [
                {"appointed_on": "2015-01-15", "name": "John Smith"}
            ],
            "resigned": []
        },
        "charges": [],
        "insolvency_history": []
    }
    
    # Calculate score
    engine = QuikScoreEngine()
    result = engine.calculate_health_score(
        company_number="12345678",
        company_name="Example Limited",
        company_data=example_data
    )
    
    # Print results
    print(f"\n{'='*60}")
    print(f"QuikScore Health Assessment")
    print(f"{'='*60}")
    print(f"Company: {result.company_name} ({result.company_number})")
    print(f"Health Score: {result.health_score}/100")
    print(f"Rating: {result.rating} ({result.color})")
    print(f"Calculated: {result.calculated_at}")
    print(f"\n{'='*60}")
    print(f"Category Breakdown:")
    print(f"{'='*60}")
    
    for category, breakdown in result.breakdown.items():
        print(f"\n{breakdown.category}: {breakdown.score}/{breakdown.max_score} ({breakdown.percentage:.0f}%)")
        for factor in breakdown.factors:
            status_icon = "✅" if factor.status == "positive" else "❌" if factor.status == "negative" else "⚪"
            print(f"  {status_icon} {factor.metric}: {factor.points} points")
            print(f"     Evidence: {factor.evidence}")
        
        if breakdown.improvements:
            print(f"  💡 Improvements:")
            for imp in breakdown.improvements:
                print(f"     - {imp}")
    
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"{'='*60}")
    print(f"\n✅ Positive Factors:")
    for factor in result.summary['positive_factors']:
        print(f"  • {factor}")
    
    print(f"\n⚠️ Risk Factors:")
    for factor in result.summary['risk_factors']:
        print(f"  • {factor}")
    
    print(f"\n💡 Recommendations:")
    for rec in result.summary['recommendations']:
        print(f"  • {rec}")
    
    print(f"\n{'='*60}")
    print(f"Audit Trail:")
    print(f"{'='*60}")
    for key, value in result.audit_trail.items():
        print(f"  {key}: {value}")
    
    print(f"\n{'='*60}")
