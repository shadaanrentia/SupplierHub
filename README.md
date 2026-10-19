# SupplierHub — PromoStandards Middleware

A full-stack application that integrates supplier product data via **PromoStandards SOAP/BulkData APIs** and synchronises products to **Odoo ERP** and/or **Lightspeed Retail (X-Series)**.

## Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌────────────────┐
│   Frontend   │────▶│     Backend      │────▶│   PostgreSQL   │
│  React/Nginx │ /api│  FastAPI/Python  │     │     (15)       │
│  port 3000   │     │    port 8001     │     │   port 5432    │
└─────────────┘     └────────┬─────────┘     └────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        PromoStandards    Odoo ERP    Lightspeed
         SOAP/Bulk        XML-RPC     REST API
```

## Quick Start with Docker

### 1. Clone & configure

```bash
cp .env.example .env
# Edit .env with your credentials (PromoStandards, Odoo, Lightspeed)
```

### 2. Build & run

```bash
docker compose up -d --build
```

### 3. Access

| Service  | URL                    |
|----------|------------------------|
| Frontend | http://localhost:3000   |
| Backend  | http://localhost:8001   |
| Postgres | localhost:5432          |

Default admin login: **admin / admin**

### Stop

```bash
docker compose down          # stop containers
docker compose down -v       # stop + delete data
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_USER` | No | DB user (default: `supplierhub`) |
| `POSTGRES_PASSWORD` | No | DB password (default: `supplierhub_pass`) |
| `POSTGRES_DB` | No | DB name (default: `supplierhub_db`) |
| `REACT_APP_BACKEND_URL` | No | Public URL for frontend API calls. Leave blank for local Docker (nginx proxies `/api` internally) |
| `PROMOSTANDARDS_USERNAME` | Yes | PromoStandards API account |
| `PROMOSTANDARDS_PASSWORD` | Yes | PromoStandards API password |
| `PROMOSTANDARDS_MEDIA_PASSWORD` | Yes | PromoStandards media password |

Lightspeed & Odoo credentials are configured via the Settings UI after login.

## Development (without Docker)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Set DATABASE_URL in .env pointing to your local PostgreSQL
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Frontend
cd frontend
yarn install
REACT_APP_BACKEND_URL=http://localhost:8001 yarn start
```

## Project Structure

```
├── backend/
│   ├── server.py              # FastAPI entrypoint (startup, CORS, routers)
│   ├── deps.py                # Shared deps (DB pool, auth, helpers)
│   ├── models.py              # Pydantic models
│   ├── routes/                # 11 route modules
│   │   ├── auth.py, suppliers.py, products.py, dashboard.py
│   │   ├── settings.py, sync.py, preprocessing.py
│   │   ├── odoo.py, lightspeed.py, categories.py, media.py
│   ├── lightspeed_service.py  # Lightspeed X-Series API client
│   ├── odoo_service.py        # Odoo XML-RPC client
│   ├── promostandards.py      # SOAP/BulkData connector
│   ├── scheduler.py           # APScheduler config
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/pages/             # React pages
│   ├── src/components/ui/     # Shadcn/UI components
│   ├── nginx.conf             # Production nginx config
│   ├── Dockerfile
│   └── package.json
├── docker/
│   └── init-db.sh             # PostgreSQL init script
├── docker-compose.yml
├── .env.example
└── README.md
```
