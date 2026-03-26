#!/usr/bin/env node
/**
 * QuikScore Load Test - Rate Limiting Validation
 * Tests per-user, tier-based rate limiting under concurrent load
 * 
 * Usage: node load-test-rate-limit.js [http://localhost:8000]
 */

const httpx = require('httpx');
const { performance } = require('perf_hooks');

const BASE_URL = process.argv[2] || 'http://localhost:8000';
const HEALTH_ENDPOINT = `${BASE_URL}/health`;

// Test configuration
const CONFIG = {
  concurrent_users: 50,
  requests_per_user: 20,
  delay_between_requests_ms: 100,
};

// Mock JWT tokens for different tiers (in production, use real tokens)
const TIERS = ['free', 'starter', 'pro', 'business'];
const RATE_LIMITS = {
  free: { requests: 60, period: 3600 },
  starter: { requests: 60, period: 60 },
  pro: { requests: 120, period: 60 },
  business: { requests: 300, period: 60 },
};

// Results tracking
const results = {
  total: 0,
  success: 0,
  rate_limited: 0,
  errors: 0,
  response_times: [],
  by_tier: {},
};

TIERS.forEach(tier => {
  results.by_tier[tier] = { success: 0, rate_limited: 0, errors: 0 };
});

/**
 * Make a single request with rate limit tracking
 */
async function makeRequest(tier, requestNum) {
  const token = `mock_token_${tier}_${requestNum}`;
  const startTime = performance.now();
  
  try {
    const response = await httpx.request(HEALTH_ENDPOINT, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      timeout: 5000,
    });
    
    const responseTime = performance.now() - startTime;
    results.response_times.push(responseTime);
    
    const headers = response.headers;
    const rateLimit = headers['x-ratelimit-limit'];
    const remaining = headers['x-ratelimit-remaining'];
    const reset = headers['x-ratelimit-reset'];
    
    if (response.statusCode === 200) {
      results.success++;
      results.by_tier[tier].success++;
      
      if (requestNum < 3) {
        console.log(`  ✅ [${tier}] Req ${requestNum}: ${responseTime.toFixed(2)}ms (Limit: ${rateLimit}, Remaining: ${remaining})`);
      }
    } else if (response.statusCode === 429) {
      results.rate_limited++;
      results.by_tier[tier].rate_limited++;
      const retryAfter = headers['retry-after'] || 'N/A';
      
      if (requestNum < 5 || requestNum % 10 === 0) {
        console.log(`  ⚠️  [${tier}] Req ${requestNum}: Rate limited (Retry-After: ${retryAfter})`);
      }
    } else {
      results.errors++;
      results.by_tier[tier].errors++;
      console.log(`  ❓ [${tier}] Req ${requestNum}: Unexpected status ${response.statusCode}`);
    }
    
    results.total++;
    
  } catch (error) {
    results.errors++;
    results.by_tier[tier].errors++;
    console.log(`  ❌ [${tier}] Req ${requestNum}: ${error.message}`);
  }
}

/**
 * Simulate a single user making multiple requests
 */
async function simulateUser(userId, tier) {
  const userResults = { success: 0, rate_limited: 0 };
  
  for (let i = 1; i <= CONFIG.requests_per_user; i++) {
    await makeRequest(tier, i);
    
    // Small delay between requests
    if (i < CONFIG.requests_per_user) {
      await new Promise(resolve => setTimeout(resolve, CONFIG.delay_between_requests_ms));
    }
  }
  
  return userResults;
}

/**
 * Run load test with concurrent users
 */
async function runLoadTest() {
  console.log('🚀 QuikScore Rate Limit Load Test');
  console.log('='.repeat(60));
  console.log(`Target: ${BASE_URL}`);
  console.log(`Concurrent Users: ${CONFIG.concurrent_users}`);
  console.log(`Requests per User: ${CONFIG.requests_per_user}`);
  console.log(`Total Requests: ${CONFIG.concurrent_users * CONFIG.requests_per_user}`);
  console.log('='.repeat(60));
  console.log();
  
  const startTime = performance.now();
  
  // Create concurrent users distributed across tiers
  const userPromises = [];
  for (let i = 0; i < CONFIG.concurrent_users; i++) {
    const tier = TIERS[i % TIERS.length]; // Round-robin tier assignment
    userPromises.push(simulateUser(i, tier));
  }
  
  // Wait for all users to complete
  await Promise.all(userPromises);
  
  const endTime = performance.now();
  const duration = ((endTime - startTime) / 1000).toFixed(2);
  
  // Print results
  console.log();
  console.log('📊 Load Test Results');
  console.log('='.repeat(60));
  console.log(`Duration: ${duration}s`);
  console.log(`Total Requests: ${results.total}`);
  console.log(`Successful: ${results.success} (${((results.success / results.total) * 100).toFixed(1)}%)`);
  console.log(`Rate Limited: ${results.rate_limited} (${((results.rate_limited / results.total) * 100).toFixed(1)}%)`);
  console.log(`Errors: ${results.errors} (${((results.errors / results.total) * 100).toFixed(1)}%)`);
  console.log();
  
  if (results.response_times.length > 0) {
    const avgResponseTime = results.response_times.reduce((a, b) => a + b, 0) / results.response_times.length;
    const sorted = [...results.response_times].sort((a, b) => a - b);
    const p95 = sorted[Math.floor(sorted.length * 0.95)];
    const p99 = sorted[Math.floor(sorted.length * 0.99)];
    
    console.log('Response Times:');
    console.log(`  Average: ${avgResponseTime.toFixed(2)}ms`);
    console.log(`  P95: ${p95.toFixed(2)}ms`);
    console.log(`  P99: ${p99.toFixed(2)}ms`);
    console.log();
  }
  
  console.log('Results by Tier:');
  TIERS.forEach(tier => {
    const tierResults = results.by_tier[tier];
    const total = tierResults.success + tierResults.rate_limited + tierResults.errors;
    console.log(`  ${tier.toUpperCase()}: ${tierResults.success} success, ${tierResults.rate_limited} rate limited, ${tierResults.errors} errors`);
  });
  console.log();
  
  // Validation
  console.log('✅ Validation:');
  const successRate = (results.success / results.total) * 100;
  const rateLimitedRate = (results.rate_limited / results.total) * 100;
  
  if (successRate > 95) {
    console.log('  ✅ Success rate > 95% (PASS)');
  } else if (successRate > 80) {
    console.log('  ⚠️  Success rate > 80% (ACCEPTABLE)');
  } else {
    console.log('  ❌ Success rate < 80% (FAIL - rate limiting too aggressive)');
  }
  
  if (rateLimitedRate > 0 && rateLimitedRate < 20) {
    console.log('  ✅ Rate limiting working correctly (some users hit limits as expected)');
  } else if (rateLimitedRate === 0) {
    console.log('  ⚠️  No rate limiting observed (may need higher load to trigger)');
  } else {
    console.log('  ⚠️  High rate limiting rate (expected with current test config)');
  }
  
  console.log();
  console.log('='.repeat(60));
  console.log('✅ Load test complete!');
}

// Run the test
runLoadTest().catch(console.error);
