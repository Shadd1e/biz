# Deployment checklist

## Supabase

- Create a new Supabase project.
- Run `supabase/schema.sql` in SQL Editor.
- Enable email/password authentication as required by the project.
- Copy the Postgres connection string into the backend environment, using SSL.
- Copy the project URL and anon key into the frontend environment.
- Copy the JWKS URL into `SUPABASE_JWKS_URL` unless a compatible JWT secret is being used.
- Keep the Supabase service/database credential out of the frontend.

## Backend on pxxl.app

- Deploy the `backend` directory as a Python web service.
- Start with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Set `DATABASE_URL`.
- Set `SUPABASE_JWKS_URL`.
- Set `DEEPSEEK_API_KEY` and `DEEPSEEK_MODEL=deepseek-chat` if interpretation is enabled.
- Set `FRONTEND_ORIGIN` to the Vercel deployment URL.
- Keep `DEV_AUTH_BYPASS=false` in production.
- Do not expose database or DeepSeek credentials to the browser.

## Frontend on Vercel

- Deploy the `frontend` directory.
- Set `VITE_API_BASE_URL` to the pxxl.app API URL plus `/api`.
- Set `VITE_SUPABASE_URL`.
- Set `VITE_SUPABASE_ANON_KEY`.
- Build with `npm run build`.

## First live verification

1. Register a user.
2. Confirm Supabase authentication succeeds.
3. Create a business profile.
4. Add a category and product.
5. Edit the product and confirm the changes persist.
6. Record a sale and verify stock decreases.
7. Delete the sale and verify stock is restored.
8. Add an expense.
9. Confirm dashboard totals match the source records.
10. Confirm the dashboard remains usable with no sales or expenses.
11. Attempt a cross-business resource request with another account and confirm it is rejected.
12. Import a valid CSV.
13. Import an invalid CSV and confirm the entire batch is rolled back.
14. Export sales, expenses and inventory CSV files.
15. Export the summary PDF.
16. Run Business Insight with DeepSeek configured.
17. Temporarily remove the DeepSeek key and confirm deterministic findings still appear.
18. Verify light, dark and system appearance settings.
19. Verify responsive behaviour on desktop and mobile widths.
