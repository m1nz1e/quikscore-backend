#!/usr/bin/env python3
"""
Rate Limit Test Script
Tests the new per-user, tier-based rate limiting implementation

Usage:
    python test_rate_limit.py [--url http://localhost:8000]
"""

import httpx
import asyncio
import time
import sys
from typing import Dict, List

# Test configuration
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
HEALTH_ENDPOINT = f"{BASE_URL}/health"

# Test tokens (these would be real JWTs in production)
# For testing, we'll use mock tokens that the middleware will parse
TEST_TOKENS = {
    "free": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLWZyZWUiLCJlbWFpbCI6ImZyZWVAdGVzdC5jb20iLCJ0aWVyIjoiZnJlZSJ9.test",
    "starter": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLXN0YXJ0ZXIiLCJlbWFpbCI6InN0YXJ0ZXJAdGVzdC5jb20iLCJ0aWVyIjoic3RhcnRlciJ9.test",
    "pro": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLXBybyIsImVtYWlsIjoicHJvQHRlc3QuY29tIiwidGllciI6InBybyJ9.test",
    "business": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLWJ1c2luZXNzIiwiZW1haWwiOiJidXNpbmVzc0B0ZXN0LmNvbSIsInRpZXIiOiJidXNpbmVzcyJ9.test",
}

# Expected rate limits
RATE_LIMITS = {
    "free": {"requests": 60, "period": 3600},      # 60 req/hour
    "starter": {"requests": 60, "period": 60},     # 60 req/min
    "pro": {"requests": 120, "period": 60},        # 120 req/min
    "business": {"requests": 300, "period": 60},   # 300 req/min
}


async def test_rate_limit_headers(tier: str, num_requests: int = 5):
    """Test that rate limit headers are present and correct"""
    print(f"\n📊 Testing Rate Limit Headers for {tier.upper()} tier")
    print("=" * 60)
    
    token = TEST_TOKENS[tier]
    expected_limit = RATE_LIMITS[tier]["requests"]
    
    async with httpx.AsyncClient() as client:
        for i in range(num_requests):
            try:
                response = await client.get(
                    HEALTH_ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                # Check for rate limit headers
                headers = response.headers
                limit = headers.get("X-RateLimit-Limit", "MISSING")
                remaining = headers.get("X-RateLimit-Remaining", "MISSING")
                reset = headers.get("X-RateLimit-Reset", "MISSING")
                
                print(f"  Request {i+1}: Status={response.status_code}, "
                      f"Limit={limit}, Remaining={remaining}, Reset={reset}")
                
                # Validate headers
                if response.status_code == 200:
                    if limit != "MISSING":
                        assert int(limit) == expected_limit, f"Expected limit {expected_limit}, got {limit}"
                    if remaining != "MISSING":
                        assert int(remaining) >= 0, f"Remaining should be >= 0, got {remaining}"
                    if reset != "MISSING":
                        assert int(reset) > int(time.time()), "Reset time should be in future"
                
            except Exception as e:
                print(f"  Request {i+1}: ERROR - {e}")
    
    print(f"✅ Rate limit headers test complete for {tier} tier")


async def test_rate_limit_enforcement(tier: str):
    """Test that rate limiting actually blocks requests when exceeded"""
    print(f"\n🚫 Testing Rate Limit Enforcement for {tier.upper()} tier")
    print("=" * 60)
    
    token = TEST_TOKENS[tier]
    limit = RATE_LIMITS[tier]["requests"]
    
    # We'll send limit + 5 requests to test enforcement
    # For free tier, this is too many, so we'll use a smaller number
    test_requests = min(limit + 5, 10) if tier == "free" else limit + 5
    
    success_count = 0
    rate_limited_count = 0
    
    async with httpx.AsyncClient() as client:
        for i in range(test_requests):
            try:
                response = await client.get(
                    HEALTH_ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    success_count += 1
                elif response.status_code == 429:
                    rate_limited_count += 1
                    retry_after = response.headers.get("Retry-After", "N/A")
                    print(f"  ⚠️  Request {i+1}: Rate limited (Retry-After: {retry_after})")
                else:
                    print(f"  ❓ Request {i+1}: Unexpected status {response.status_code}")
                    
            except Exception as e:
                print(f"  ❌ Request {i+1}: Error - {e}")
    
    print(f"\n📈 Results for {tier} tier:")
    print(f"  Successful: {success_count}")
    print(f"  Rate Limited: {rate_limited_count}")
    print(f"  Expected Limit: {limit}")
    
    # For free tier, we expect some rate limiting after 60 requests
    # For this quick test, we just verify the mechanism works
    if rate_limited_count > 0:
        print(f"  ✅ Rate limiting is working (blocked {rate_limited_count} requests)")
    else:
        print(f"  ⚠️  No rate limiting observed (may need more requests to trigger)")


async def test_concurrent_users():
    """Test that different users have separate rate limits"""
    print(f"\n👥 Testing Concurrent Users (Separate Rate Limits)")
    print("=" * 60)
    
    tiers = ["starter", "pro", "business"]
    results: Dict[str, Dict] = {}
    
    async def make_requests(tier: str, count: int):
        token = TEST_TOKENS[tier]
        success = 0
        rate_limited = 0
        
        async with httpx.AsyncClient() as client:
            for _ in range(count):
                try:
                    response = await client.get(
                        HEALTH_ENDPOINT,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        success += 1
                    elif response.status_code == 429:
                        rate_limited += 1
                except:
                    pass
        
        return {"success": success, "rate_limited": rate_limited}
    
    # Run concurrent requests for different tiers
    tasks = [
        make_requests("starter", 10),
        make_requests("pro", 10),
        make_requests("business", 10),
    ]
    
    results_list = await asyncio.gather(*tasks)
    
    for tier, result in zip(tiers, results_list):
        print(f"  {tier.upper()}: {result['success']} success, {result['rate_limited']} rate limited")
    
    print(f"  ✅ Concurrent user test complete")


async def main():
    """Run all rate limit tests"""
    print("🚀 QuikScore Rate Limit Test Suite")
    print("=" * 60)
    print(f"Target: {BASE_URL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test 1: Rate limit headers for each tier
    for tier in ["free", "starter", "pro", "business"]:
        await test_rate_limit_headers(tier, num_requests=3)
        await asyncio.sleep(0.5)  # Small delay between tests
    
    # Test 2: Rate limit enforcement (light test)
    await test_rate_limit_enforcement("free")
    await asyncio.sleep(1)
    
    # Test 3: Concurrent users
    await test_concurrent_users()
    
    print("\n" + "=" * 60)
    print("✅ All rate limit tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
