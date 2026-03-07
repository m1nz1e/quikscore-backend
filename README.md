# QuikScore Backend API

FastAPI backend for AI-powered UK company health scores.

## 🚀 Quick Start

### Local Development

```bash
# Create virtual environment
python -m venv .venv

# Activate
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn main:app --reload --port 8001
```

Visit: http://localhost:8001/docs

## 📦 Deployment

### Render

1. Connect this GitHub repo to Render
2. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Python Version:** 3.11
3. Add environment variables (see below)

### Environment Variables

Required:
```
COMPANIES_HOUSE_API_KEY=your_key
DATABASE_URL=postgresql://user:pass@host/db
REDIS_URL=redis://localhost:6379
JWT_SECRET=your-secret-key-min-32-chars
```

Optional:
```
FCA_API_KEY=your_key
LAND_REGISTRY_API_KEY=your_key
EPC_API_KEY=your_key
```

## 📡 API Endpoints

- `GET /` - API info
- `GET /health` - Health check
- `POST /api/companies/search` - Search companies
- `GET /api/companies/{number}` - Get company details
- `POST /api/health-score` - Generate health score
- `GET /docs` - Interactive API docs (Swagger)

## 🧪 Testing

```bash
# Run tests
pytest

# Test with curl
curl https://your-backend-url.onrender.com/health
curl https://your-backend-url.onrender.com/api/companies/search \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"TESCO","items_per_page":5}'
```

## 📄 License

Proprietary - QuikScore Limited
