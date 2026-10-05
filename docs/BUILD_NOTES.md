# Build notes

## What was retained from the original project

The remake retains the original functional scope that is supported by the project source: authentication, business setup, categories, products/inventory, sales, expenses, dashboard analytics, rule-based decision support, reports, CSV export, PDF summary reporting, settings and optional AI business interpretation.

The new implementation does not carry forward the old ASP.NET Core authentication/database implementation. Supabase Auth and the new Supabase PostgreSQL schema are the source of identity and persistence for the remake.

## What changed

- Backend: ASP.NET Core/.NET 8 → Python/FastAPI.
- Authentication: bespoke JWT/password storage → Supabase Auth.
- Database hosting: application-managed PostgreSQL → Supabase PostgreSQL.
- Frontend: React/TypeScript retained, with the interface rebuilt around a restrained business workflow.
- Deployment target: Vercel frontend and pxxl.app backend.
- AI: DeepSeek is an optional interpretation service behind the backend boundary.

## Decision-support boundary

The backend calculates revenue, expenses, estimated profit, stock status, trends, channel totals, top products and deterministic findings. DeepSeek receives only the controlled analytical context and is instructed not to invent values, products, dates, causes or forecasts.

If DeepSeek is unavailable, the deterministic findings remain available. The AI response is not treated as the source of truth.

## Data integrity and security boundary

- Browser-visible configuration contains only the Supabase URL and anon key plus the API URL.
- Database credentials and the DeepSeek credential remain on the backend.
- API requests require a valid Supabase access token unless development bypass is explicitly enabled.
- Business records are scoped to the authenticated owner on the backend.
- Supabase RLS policies are included in the schema for direct database access.
- Sales stock changes lock the product row during create/delete/import operations.
- CSV uploads are size- and row-limited and transactionally rolled back on validation failure.

## Report relationship

The report draft in `docs/` is a working academic draft, not the final submitted report. Final screenshots, observed test results and deployment evidence must be added only after the live application has been run and verified.
