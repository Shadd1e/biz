# BizInsight DSS — Clean-Sweep Remake

BizInsight is a web-based, data-driven Decision Support System for small business operations. It records products, inventory, sales and expenses, turns those records into descriptive and diagnostic analytics, and presents the results through a restrained interactive dashboard.

The system supports the human decision-maker. It does not make business decisions on the user's behalf and it does not use predictive forecasting as part of the core project scope.

## Final architecture

- **Presentation:** React + TypeScript + Vite
- **Application/logic:** Python + FastAPI + Pydantic + SQLAlchemy
- **Data:** Supabase PostgreSQL
- **Authentication:** Supabase Auth
- **Decision support:** deterministic calculations and rule-based findings
- **Interpretation:** optional DeepSeek service through the backend only
- **Frontend deployment:** Vercel
- **Backend deployment:** pxxl.app

DeepSeek never directly queries the database. The backend calculates the authoritative business figures first, then sends a controlled analytical context to the interpretation service. If the provider is unavailable, deterministic DSS findings remain available.

## Main functions

- Supabase email/password authentication
- Business workspace setup and editing
- Account name and password management through Supabase Auth
- Product categories
- Product and inventory management
- Sales recording with server-side total calculation and stock movement
- Sale deletion with stock restoration
- Expense tracking
- Dashboard revenue, expenses, estimated profit, sales count, trends, channels, top products and low-stock findings
- Rule-based decision-support findings
- Optional DeepSeek business interpretation
- Sales, expense and inventory CSV export
- Summary PDF export
- Transactional CSV import for products, sales and expenses
- Currency, dashboard-period, alert and appearance settings
- Responsive desktop/mobile interface

## Design direction

The interface uses a restrained warm neutral and dull-gold palette with solid surfaces, clear hierarchy and limited decoration. The design deliberately avoids decorative gradients, generic AI imagery, sparkle-based AI branding, excessive pills, excessive cards, glassmorphism and meaningless dashboard metrics.

## Local setup

### Backend

```bash
cd backend
python -m venv .venv
# activate the environment using the command for your shell
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Create `backend/.env` from `.env.example` and provide the Supabase database URL, Supabase JWKS URL, frontend origin and optional DeepSeek credentials.

### Supabase

Run `supabase/schema.sql` in the Supabase SQL Editor. The schema enables row-level security and scopes direct database access to the authenticated business owner.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Create `frontend/.env` from `.env.example` and set the API base URL, Supabase URL and Supabase anon key.

## Deployment

### Vercel

- Root directory: `frontend`
- Build command: `npm run build`
- Output directory: `dist`
- Environment variables: `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`

### pxxl.app

- Root directory: `backend`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment variables: `DATABASE_URL`, `SUPABASE_JWKS_URL`, `FRONTEND_ORIGIN`, and optional DeepSeek variables

No Docker dependency is required by this remake.

## CSV formats

- **Products:** `name, category, description, cost_price, selling_price, current_stock, reorder_level, sku`
- **Expenses:** `date, name, category, amount`
- **Sales:** `date, product_id, quantity, unit_price, channel, payment_method`

Imports are validated as a batch. A failed row causes the transaction to roll back rather than partially importing the file. Uploads are limited to 5 MB and 5,000 rows.

## Verification

Backend syntax, tests and FastAPI route registration were verified in the build environment. The frontend production build could not be run in this environment because access to the external npm registry timed out. Complete live verification still requires the user's Supabase, Vercel, pxxl.app and optional DeepSeek credentials.
