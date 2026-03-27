#!/bin/bash
# QuikScore Anti-Scraper Security Tests
# Tests Tier 1 security measures after deployment

BASE_URL="https://quikscore.onrender.com"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "🛡️  QuikScore Anti-Scraper Tests"
echo "========================================"
echo ""

# Test 1: Blocked User-Agent (python-requests)
echo -e "${YELLOW}Test 1: Blocked User-Agent (python-requests)${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "User-Agent: python-requests/2.28.0" "$BASE_URL/api/company/12099719")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "403" ]; then
    echo -e "${GREEN}✅ PASS${NC} - Got 403 Forbidden as expected"
    echo "Response: $BODY"
else
    echo -e "${RED}❌ FAIL${NC} - Expected 403, got $HTTP_CODE"
fi
echo ""

# Test 2: Blocked User-Agent (curl)
echo -e "${YELLOW}Test 2: Blocked User-Agent (curl/)${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "User-Agent: curl/7.68.0" "$BASE_URL/health")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "403" ]; then
    echo -e "${GREEN}✅ PASS${NC} - Got 403 Forbidden as expected"
else
    echo -e "${RED}❌ FAIL${NC} - Expected 403, got $HTTP_CODE"
fi
echo ""

# Test 3: Normal Browser User-Agent (should work)
echo -e "${YELLOW}Test 3: Normal Browser User-Agent${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" "$BASE_URL/health")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✅ PASS${NC} - Got 200 OK as expected"
    echo "Response: $BODY"
else
    echo -e "${RED}❌ FAIL${NC} - Expected 200, got $HTTP_CODE"
fi
echo ""

# Test 4: Empty User-Agent (should be blocked)
echo -e "${YELLOW}Test 4: Empty User-Agent${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "User-Agent:" "$BASE_URL/health")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "403" ]; then
    echo -e "${GREEN}✅ PASS${NC} - Got 403 Forbidden as expected"
else
    echo -e "${RED}❌ FAIL${NC} - Expected 403, got $HTTP_CODE"
fi
echo ""

# Test 5: Honeypot Endpoint
echo -e "${YELLOW}Test 5: Honeypot Endpoint (/admin/users)${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "User-Agent: Mozilla/5.0" "$BASE_URL/admin/users")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "404" ]; then
    echo -e "${GREEN}✅ PASS${NC} - Got 404 Not Found (honeypot triggered)"
else
    echo -e "${RED}❌ FAIL${NC} - Expected 404, got $HTTP_CODE"
fi
echo ""

# Test 6: Other Honeypot Endpoints
echo -e "${YELLOW}Test 6: Honeypot Endpoints (/.env, /wp-admin)${NC}"
for endpoint in "/.env" "/wp-admin" "/phpmyadmin" "/backup.sql"; do
    RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL$endpoint")
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    if [ "$HTTP_CODE" = "404" ]; then
        echo -e "${GREEN}✅${NC} $endpoint - 404 (honeypot)"
    else
        echo -e "${RED}❌${NC} $endpoint - Expected 404, got $HTTP_CODE"
    fi
done
echo ""

# Test 7: Rate Limiting (Unauthenticated - 20 req/min)
echo -e "${YELLOW}Test 7: Rate Limiting (Unauthenticated - 20 req/min)${NC}"
echo "Making 25 rapid requests to /health..."
RATE_LIMITED=false
for i in {1..25}; do
    RESPONSE=$(curl -s -w "\n%{http_code}" -H "User-Agent: Mozilla/5.0" "$BASE_URL/health")
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    if [ "$HTTP_CODE" = "429" ]; then
        echo -e "${GREEN}✅ Rate limited at request $i${NC}"
        RATE_LIMITED=true
        break
    fi
done

if [ "$RATE_LIMITED" = false ]; then
    echo -e "${RED}❌ FAIL${NC} - No rate limiting detected after 25 requests"
else
    echo -e "${GREEN}✅ PASS${NC} - Rate limiting working (429 after ~20 requests)"
fi
echo ""

# Test 8: Admin Endpoints
echo -e "${YELLOW}Test 8: Admin Endpoints (Security Logs)${NC}"
echo "Testing /admin/security-summary..."
RESPONSE=$(curl -s -H "User-Agent: Mozilla/5.0" "$BASE_URL/admin/security-summary")
if echo "$RESPONSE" | grep -q "scraper_detections"; then
    echo -e "${GREEN}✅ PASS${NC} - Security summary endpoint working"
    echo "Response: $RESPONSE" | head -c 200
else
    echo -e "${RED}❌ FAIL${NC} - Security summary not working"
    echo "Response: $RESPONSE"
fi
echo ""
echo ""

# Test 9: Scraper Detection Logs
echo -e "${YELLOW}Test 9: Scraper Detection Logs${NC}"
RESPONSE=$(curl -s -H "User-Agent: Mozilla/5.0" "$BASE_URL/admin/scraper-logs?limit=5")
if echo "$RESPONSE" | grep -q "logs"; then
    echo -e "${GREEN}✅ PASS${NC} - Scraper logs endpoint working"
    echo "Recent logs: $RESPONSE" | head -c 300
else
    echo -e "${RED}❌ FAIL${NC} - Scraper logs not working"
fi
echo ""
echo ""

echo "========================================"
echo "📊 Test Summary"
echo "========================================"
echo "All tests completed. Check results above."
echo ""
echo "Next steps:"
echo "1. Verify logs in Render dashboard"
echo "2. Monitor honeypot_triggers.log for bot activity"
echo "3. Review scraper_detection.log for patterns"
echo ""
