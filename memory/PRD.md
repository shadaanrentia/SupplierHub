# SupplierHub - PromoStandards Middleware PRD

## Original Problem Statement
Build a middleware application that integrates supplier product data using PromoStandards SOAP APIs and synchronizes selected products into Odoo ERP. Central staging database, admin curation interface, automated sync jobs.

## Architecture
- **Backend**: FastAPI (Python) with PostgreSQL — **Modular router architecture**
  - `server.py`: Slim entrypoint (~175 lines) — startup, CORS, router registration
  - `deps.py`: Shared dependencies — DB pool, helpers, auth deps, sync log helpers
  - `models.py`: All Pydantic request/response models
  - `routes/`: 11 route modules (auth, suppliers, products, dashboard, settings, sync, odoo, lightspeed, categories, preprocessing, media)
- **Frontend**: React with Shadcn UI, Tailwind CSS, dark theme
- **Database**: PostgreSQL 15 (users, suppliers, products, product_variants, product_media, sync_logs, settings, odoo_categories, category_mapping, product_sync_status)
- **SOAP Client**: Raw XML over HTTP with XML escaping (no WSDL dependency - bypasses WAF blocking)
- **Odoo Integration**: XML-RPC client for creating/updating products, variants, inventory, and images
- **Lightspeed Integration**: REST API (date-based versioning `2026-01`) at `{domain_prefix}.retail.lightspeed.app` with OAuth 2.0 or Personal Token
- **Flow**: PromoStandards SOAP APIs → Raw XML Connector → PostgreSQL Staging → Admin Curation → Pre-Processing → Odoo ERP / Lightspeed Retail

## User Personas
- **Admin**: Manages suppliers, curates products, maps categories, triggers syncs, configures Odoo
- **System**: Automated background sync jobs for products/inventory/pricing/media

## Core Requirements (Static)
1. Multi-supplier Integration via PromoStandards (Product Data, Inventory, Pricing, Media Content)
2. Centralized staging database for all supplier product data
3. Data normalization layer (XML→JSON)
4. Admin product curation dashboard with filters
5. Odoo ERP integration layer (create/update products with full details)
6. Background sync jobs (products 24h, inventory 30min, pricing 12h)
7. REST API layer for all operations
8. Logging and error handling
9. Category mapping between supplier and Odoo e-commerce categories
10. Product pre-processing with configurable markup and validation

## What's Been Implemented

### July 28, 2026 - Lightspeed OAuth 2.0 & API Version Update
- **OAuth 2.0 (Private App) Support**: Full authorization code flow for Lightspeed X-Series
  - `GET /api/lightspeed/oauth/authorize` — generates Lightspeed authorization URL
  - `GET /api/lightspeed/oauth/callback` — handles redirect, exchanges code for tokens
  - `POST /api/lightspeed/oauth/disconnect` — clears stored OAuth tokens
  - Automatic token refresh when access token expires
  - Both OAuth and Personal Token auth supported simultaneously
- **API Version Migration**: Changed from deprecated `v2.0` to date-based `2026-01`
  - All API calls now use `/api/2026-01/` path
  - Variant creation updated to use `variant_definitions` with `attribute_id`
  - Variant attributes (Color, Size) auto-created via `/variant_attributes` endpoint
- **Settings UI Updated**: New Lightspeed section with:
  - OAuth 2.0 (Private App) section: Client ID, Client Secret, "Connect to Lightspeed" button
  - Personal Token (Legacy) section for Plus plan accounts
  - OAuth Connected badge and Disconnect button
  - OAuth callback handler for redirect-based auth
- **DB Schema**: Added columns: `lightspeed_client_id`, `lightspeed_client_secret`, `lightspeed_access_token`, `lightspeed_refresh_token`, `lightspeed_token_expires_at`
- **Testing**: 10/10 backend tests passed, 100% frontend verification

### July 24, 2026 - Server Decomposition & Sync Progress Tracker
- **Server Decomposition**: Broke 3300-line monolithic `server.py` into modular architecture
- **Sync Progress Tracker**: Live progress bar for running sync jobs
- **Lightspeed API URL Fix**: Changed from Ecwid to X-Series

### July 24, 2026 - Lightspeed Retail (X-Series) Integration (Phase 2)
- Multi-Platform Architecture with provider-based integration
- Product CRUD, variant sync, categories, image upload

### March 27, 2026 - APScheduler & Auto-Push to Odoo
- Automated Background Sync Jobs via APScheduler
- Auto-push to Odoo after BulkData sync

### March 16, 2026 - BulkData Sync Feature Added
- BulkData Service 1.0 Integration
- Tested with ATC sandbox (2 products synced)

### March 16, 2026 - Odoo Sync Complete
- Fixed Image Sync, Inventory Sync, Cost Price Sync

### December 2025 - PostgreSQL Migration & Final Features
- Migrated from MongoDB to PostgreSQL
- Axios Interceptor, Product Search, Warehouse-Specific Inventory

### March 2026 - Authentication & User Management
- Login, Registration, Password Reset, Admin User Management

## Known Issues
1. **SanMar API CAPTCHA Protected**: CDN blocks server-side requests. User needs to whitelist server IP.
2. **Athletic Knit API 503**: Supplier endpoints returning errors.
3. **PostgreSQL Non-Persistent**: Preview environment data resets on restart.

## Prioritized Backlog

### P0 (Critical - Blocked)
- [ ] Get supplier IP whitelisting (ATC, S&S, etc.) - requires user to contact suppliers

### P1 (Important)
- [x] Lightspeed OAuth 2.0 integration ✅ (July 28, 2026)
- [x] API version migration to 2026-01 ✅ (July 28, 2026)
- [ ] **Live Product Push Testing**: User needs to click "Connect to Lightspeed" in Settings and authorize, then push real products
- [ ] Re-sync products after IP whitelisting

### P2 (Nice to have)
- [ ] Image retry mechanism for failed downloads
- [ ] Sync Scheduling Dashboard (calendar view of upcoming jobs)
- [ ] Add export functionality (CSV/Excel)
- [ ] Add webhook notifications for sync failures

## Credentials
- **Admin Portal**: admin / admin
- **ATC Sandbox**: sandbox / sandbox123
- **Lightspeed X-Series**: Domain=redleafssports, OAuth Private App (client_id + client_secret)
- **Odoo**: URL=odoo.redleafssports.ca, DB=RedLeafsPOC27012026
