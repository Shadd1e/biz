# BizInsight DSS Backend

FastAPI backend for the BizInsight browser application. It provides authenticated business setup, categories, products, sales, expenses, dashboard calculations, CSV import/export, report summaries, a summary-PDF export, and optional DeepSeek explanations.

## Local setup

1. Create a Python virtual environment.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and configure the values.
4. Apply `../supabase/schema.sql` to the Supabase project.
5. Start the API from this `backend` directory: `uvicorn app.main:app --reload --port 8000`.
6. Open `/docs` for the generated API reference and `/health` for a health check.

## Required configuration

- `DATABASE_URL`: PostgreSQL connection string for the Supabase database.
- `SUPABASE_URL`: Supabase project URL.
- `SUPABASE_ANON_KEY`: public anon key used by the backend to verify the access token against Supabase Auth's `/auth/v1/user` endpoint.
- `FRONTEND_ORIGIN`: comma-separated exact frontend origins allowed by CORS.
- `DEEPSEEK_API_KEY`: optional; omit to use the deterministic fallback.
- `DEEPSEEK_BASE_URL`: optional DeepSeek API base URL.

Never expose a database password or DeepSeek key in frontend environment variables. For production, use platform-managed secrets and TLS-enabled database connections.

## Tests

From this directory, run `PYTHONPATH=. pytest -q`. Tests that require live Supabase credentials or a configured PostgreSQL database are not included in the passing local test count and must be run against a non-production test project before release.

## Integration notes

The frontend expects the API base URL to end in `/api`, for example `http://localhost:8000/api`. The dashboard and report summary routes are registered before the dynamic one-segment resource route so they resolve correctly. Product removal archives products to preserve historical sales references. The optional in-app PDF export is not the academic project report.
