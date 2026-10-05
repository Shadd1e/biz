create extension if not exists pgcrypto;

create table if not exists public.businesses (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  business_type text not null default 'Retail',
  description text,
  phone text,
  email text,
  address text,
  created_at timestamptz not null default now()
);

create unique index if not exists businesses_owner_unique on public.businesses(owner_id);

create table if not exists public.business_settings (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null unique references public.businesses(id) on delete cascade,
  currency text not null default 'NGN',
  dashboard_period integer not null default 30 check (dashboard_period between 7 and 365),
  recommendations_enabled boolean not null default true,
  ai_enabled boolean not null default true,
  low_stock_alerts boolean not null default true,
  expense_alerts boolean not null default true,
  sales_alerts boolean not null default true,
  theme text not null default 'system'
);

create table if not exists public.categories (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null,
  description text,
  created_at timestamptz not null default now()
);

create table if not exists public.products (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  category_id uuid not null references public.categories(id) on delete restrict,
  name text not null,
  description text,
  cost_price numeric(14,2) not null default 0,
  selling_price numeric(14,2) not null default 0,
  current_stock integer not null default 0,
  reorder_level integer not null default 5,
  sku text,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.sales (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  product_id uuid not null references public.products(id) on delete restrict,
  quantity integer not null check (quantity > 0),
  unit_price numeric(14,2) not null check (unit_price >= 0),
  total_amount numeric(14,2) not null check (total_amount >= 0),
  sales_channel text not null default 'Physical Store',
  payment_method text not null default 'Cash',
  sale_date timestamptz not null,
  created_at timestamptz not null default now()
);

create table if not exists public.expenses (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  name text not null,
  category text not null,
  amount numeric(14,2) not null check (amount > 0),
  expense_date timestamptz not null,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists public.recommendation_history (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  message text not null,
  kind text not null,
  generated_at timestamptz not null default now()
);

create table if not exists public.ai_insight_runs (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  status text not null,
  response_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

drop policy if exists "owner businesses" on public.businesses;
drop policy if exists "owner settings" on public.business_settings;
drop policy if exists "owner categories" on public.categories;
drop policy if exists "owner products" on public.products;
drop policy if exists "owner sales" on public.sales;
drop policy if exists "owner expenses" on public.expenses;
drop policy if exists "owner recommendations" on public.recommendation_history;
drop policy if exists "owner ai runs" on public.ai_insight_runs;

alter table public.businesses enable row level security;
alter table public.business_settings enable row level security;
alter table public.categories enable row level security;
alter table public.products enable row level security;
alter table public.sales enable row level security;
alter table public.expenses enable row level security;
alter table public.recommendation_history enable row level security;
alter table public.ai_insight_runs enable row level security;

create policy "owner businesses" on public.businesses for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());
create policy "owner settings" on public.business_settings for all using (business_id in (select id from public.businesses where owner_id=auth.uid())) with check (business_id in (select id from public.businesses where owner_id=auth.uid()));
create policy "owner categories" on public.categories for all using (business_id in (select id from public.businesses where owner_id=auth.uid())) with check (business_id in (select id from public.businesses where owner_id=auth.uid()));
create policy "owner products" on public.products for all using (business_id in (select id from public.businesses where owner_id=auth.uid())) with check (business_id in (select id from public.businesses where owner_id=auth.uid()));
create policy "owner sales" on public.sales for all using (business_id in (select id from public.businesses where owner_id=auth.uid())) with check (business_id in (select id from public.businesses where owner_id=auth.uid()));
create policy "owner expenses" on public.expenses for all using (business_id in (select id from public.businesses where owner_id=auth.uid())) with check (business_id in (select id from public.businesses where owner_id=auth.uid()));
create policy "owner recommendations" on public.recommendation_history for all using (business_id in (select id from public.businesses where owner_id=auth.uid())) with check (business_id in (select id from public.businesses where owner_id=auth.uid()));
create policy "owner ai runs" on public.ai_insight_runs for all using (business_id in (select id from public.businesses where owner_id=auth.uid())) with check (business_id in (select id from public.businesses where owner_id=auth.uid()));
