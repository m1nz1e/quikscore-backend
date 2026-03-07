"""
QuikScore Database Schema
PostgreSQL with Neon.tech
"""

SCHEMA_SQL = """
-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    company_name VARCHAR(255),
    stripe_customer_id VARCHAR(255),
    subscription_tier VARCHAR(50) DEFAULT 'free',
    subscription_status VARCHAR(50) DEFAULT 'inactive',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Companies table (cached from Companies House)
CREATE TABLE IF NOT EXISTS companies (
    company_number VARCHAR(20) PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    company_status VARCHAR(50),
    company_type VARCHAR(50),
    incorporation_date DATE,
    registered_office_address JSONB,
    sic_codes JSONB,
    accounts JSONB,
    confirmation_statement JSONB,
    officers_count INTEGER DEFAULT 0,
    health_score INTEGER,
    health_score_reasoning JSONB,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cached_until TIMESTAMP
);

-- Health score history
CREATE TABLE IF NOT EXISTS health_score_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_number VARCHAR(20) REFERENCES companies(company_number),
    health_score INTEGER NOT NULL,
    scoring_factors JSONB,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User searches
CREATE TABLE IF NOT EXISTS user_searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    search_query VARCHAR(255),
    company_number VARCHAR(20),
    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Company monitoring
CREATE TABLE IF NOT EXISTS company_monitoring (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    company_number VARCHAR(20) REFERENCES companies(company_number),
    alert_types JSONB DEFAULT '["filing_overdue", "officer_change", "status_change"]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- API keys
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    tier VARCHAR(50) DEFAULT 'pro',
    rate_limit INTEGER DEFAULT 1000,
    calls_used INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    stripe_subscription_id VARCHAR(255),
    stripe_price_id VARCHAR(255),
    status VARCHAR(50),
    current_period_start TIMESTAMP,
    current_period_end TIMESTAMP,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    canceled_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies USING gin(to_tsvector('english', company_name));
CREATE INDEX IF NOT EXISTS idx_companies_health_score ON companies(health_score);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_monitoring_user ON company_monitoring(user_id);
CREATE INDEX IF NOT EXISTS idx_searches_user ON user_searches(user_id);
CREATE INDEX IF NOT EXISTS idx_history_company ON health_score_history(company_number);

-- Insert sample data (for testing)
INSERT INTO users (email, password_hash, name, subscription_tier) 
VALUES 
    ('test@example.com', 'hashed_password_here', 'Test User', 'free')
ON CONFLICT (email) DO NOTHING;
"""

def get_schema():
    """Return the database schema SQL"""
    return SCHEMA_SQL

def get_migration_sql():
    """Return migration SQL for existing databases"""
    return """
    -- Add new columns if they don't exist
    ALTER TABLE companies ADD COLUMN IF NOT EXISTS health_score INTEGER;
    ALTER TABLE companies ADD COLUMN IF NOT EXISTS health_score_reasoning JSONB;
    ALTER TABLE companies ADD COLUMN IF NOT EXISTS cached_until TIMESTAMP;
    
    -- Create indexes if they don't exist
    CREATE INDEX IF NOT EXISTS idx_companies_health_score ON companies(health_score);
    """
