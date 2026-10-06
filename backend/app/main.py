from __future__ import annotations

import csv
import io
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

import httpx
import jwt
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, JSON, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', case_sensitive=False)
    database_url: str = ''
    supabase_url: str = ''
    supabase_jwt_secret: str = ''
    supabase_jwks_url: str = ''
    deepseek_api_key: str = ''
    deepseek_model: str = 'deepseek-chat'
    deepseek_base_url: str = 'https://api.deepseek.com'
    frontend_origin: str = 'http://localhost:5173'
    # Exact production/stable origins go in FRONTEND_ORIGIN. This regex also
    # permits Vercel preview deployments for this BizInsight frontend project.
    # It is intentionally scoped to this project/owner rather than allowing
    # every *.vercel.app origin.
    frontend_origin_regex: str = r'^https://biz-[a-z0-9-]+-shadrach-nelsons-projects\.vercel\.app$'
    dev_auth_bypass: bool = False
    dev_user_id: str = '00000000-0000-0000-0000-000000000001'

settings = Settings()


def engine_url() -> str:
    if not settings.database_url:
        raise RuntimeError('DATABASE_URL is required')
    return settings.database_url.replace('postgres://', 'postgresql+psycopg://', 1).replace('postgresql://', 'postgresql+psycopg://', 1)

engine = create_engine(engine_url(), pool_pre_ping=True) if settings.database_url else None
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False) if engine else None


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = 'businesses'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(160))
    business_type: Mapped[str] = mapped_column(String(120), default='Retail')
    description: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    settings: Mapped['BusinessSettings'] = relationship(back_populates='business', uselist=False, cascade='all, delete-orphan')


class BusinessSettings(Base):
    __tablename__ = 'business_settings'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(ForeignKey('businesses.id', ondelete='CASCADE'), unique=True)
    currency: Mapped[str] = mapped_column(String(8), default='NGN')
    dashboard_period: Mapped[int] = mapped_column(Integer, default=30)
    recommendations_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    low_stock_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    expense_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    sales_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str] = mapped_column(String(16), default='system')
    business: Mapped[Business] = relationship(back_populates='settings')


class Category(Base):
    __tablename__ = 'categories'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(ForeignKey('businesses.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Product(Base):
    __tablename__ = 'products'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(ForeignKey('businesses.id', ondelete='CASCADE'), index=True)
    category_id: Mapped[UUID] = mapped_column(ForeignKey('categories.id', ondelete='RESTRICT'))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[Optional[str]] = mapped_column(Text)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    current_stock: Mapped[int] = mapped_column(Integer, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=5)
    sku: Mapped[Optional[str]] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Sale(Base):
    __tablename__ = 'sales'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(ForeignKey('businesses.id', ondelete='CASCADE'), index=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey('products.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    sales_channel: Mapped[str] = mapped_column(String(40), default='Physical Store')
    payment_method: Mapped[str] = mapped_column(String(40), default='Cash')
    sale_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Expense(Base):
    __tablename__ = 'expenses'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(ForeignKey('businesses.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    expense_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RecommendationHistory(Base):
    __tablename__ = 'recommendation_history'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(ForeignKey('businesses.id', ondelete='CASCADE'), index=True)
    message: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AiInsightRun(Base):
    __tablename__ = 'ai_insight_runs'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    business_id: Mapped[UUID] = mapped_column(ForeignKey('businesses.id', ondelete='CASCADE'), index=True)
    status: Mapped[str] = mapped_column(String(20))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ---------- API schemas ----------
class BusinessIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    business_type: str = 'Retail'
    description: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None

class BusinessOut(BusinessIn):
    id: UUID
    model_config = ConfigDict(from_attributes=True)

class SettingsIn(BaseModel):
    currency: str = 'NGN'
    dashboard_period: int = Field(default=30, ge=7, le=365)
    recommendations_enabled: bool = True
    ai_enabled: bool = True
    low_stock_alerts: bool = True
    expense_alerts: bool = True
    sales_alerts: bool = True
    theme: str = 'system'

class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None

class ProductIn(BaseModel):
    category_id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    cost_price: Decimal = Field(ge=0)
    selling_price: Decimal = Field(ge=0)
    current_stock: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=5, ge=0)
    sku: str | None = None
    is_active: bool = True

class SaleIn(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    sales_channel: str = 'Physical Store'
    payment_method: str = 'Cash'
    sale_date: datetime | None = None

class ExpenseIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)
    expense_date: datetime | None = None
    notes: str | None = None

class InsightOut(BaseModel):
    available: bool
    summary: str
    key_findings: list[str]
    positive_signals: list[str]
    attention_items: list[str]
    recommendations: list[str]
    generated_at: datetime


security = HTTPBearer(auto_error=False)


def get_db() -> Session:
    if SessionLocal is None:
        raise HTTPException(500, 'DATABASE_URL is not configured.')
    with SessionLocal() as db:
        yield db


_JWKS_CACHE_TTL = timedelta(hours=1)
_ALLOWED_JWKS_ALGORITHMS = {'RS256', 'ES256'}
_jwks_cache: dict[str, Any] = {'keys': None, 'expires': datetime.min.replace(tzinfo=timezone.utc)}


def _supabase_jwks_url() -> str:
    """Return the configured JWKS URL, deriving Supabase's standard URL when possible."""
    if settings.supabase_jwks_url:
        return settings.supabase_jwks_url
    if settings.supabase_url:
        return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return ''


def _load_jwks(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Load and cache the Supabase signing keys, refreshing on demand."""
    now = datetime.now(timezone.utc)
    if not force_refresh and _jwks_cache['keys'] is not None and now < _jwks_cache['expires']:
        return _jwks_cache['keys']

    jwks_url = _supabase_jwks_url()
    if not jwks_url:
        raise RuntimeError('Supabase JWKS URL is not configured.')

    response = httpx.get(jwks_url, timeout=5)
    response.raise_for_status()
    data = response.json()
    keys = data.get('keys')
    if not isinstance(keys, list) or not keys:
        raise RuntimeError('Supabase JWKS response contains no signing keys.')

    _jwks_cache['keys'] = keys
    _jwks_cache['expires'] = now + _JWKS_CACHE_TTL
    return keys


def _verify_jwks_token(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    algorithm = header.get('alg')
    kid = header.get('kid')

    if algorithm not in _ALLOWED_JWKS_ALGORITHMS:
        raise ValueError('Unsupported JWT signing algorithm.')
    if not kid:
        raise ValueError('JWT signing key id is missing.')

    keys = _load_jwks()
    key = next((candidate for candidate in keys if candidate.get('kid') == kid), None)
    if key is None:
        # Supabase can rotate signing keys. Refresh once before rejecting a new kid.
        keys = _load_jwks(force_refresh=True)
        key = next((candidate for candidate in keys if candidate.get('kid') == kid), None)
    if key is None:
        raise ValueError('JWT signing key was not found.')

    key_algorithm = key.get('alg')
    if key_algorithm and key_algorithm != algorithm:
        raise ValueError('JWT signing algorithm does not match the signing key.')

    key_type = key.get('kty')
    if algorithm == 'RS256':
        if key_type != 'RSA':
            raise ValueError('RS256 requires an RSA signing key.')
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
    else:  # ES256
        if key_type != 'EC':
            raise ValueError('ES256 requires an EC signing key.')
        public_key = jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(key))

    return jwt.decode(
        token,
        public_key,
        algorithms=[algorithm],
        audience='authenticated',
    )


def current_user_id(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> UUID:
    if settings.dev_auth_bypass:
        return UUID(settings.dev_user_id)
    if not credentials:
        raise HTTPException(401, 'Authentication required.')

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get('alg')

        # Legacy Supabase projects may still use HS256. Only use the configured
        # legacy secret for an explicitly HS256 token; asymmetric Supabase
        # signing keys are verified through JWKS below.
        if algorithm == 'HS256' and settings.supabase_jwt_secret:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=['HS256'],
                audience='authenticated',
            )
        elif algorithm in _ALLOWED_JWKS_ALGORITHMS:
            payload = _verify_jwks_token(token)
        else:
            raise ValueError('Unsupported JWT signing algorithm.')

        subject = payload.get('sub')
        if not subject:
            raise ValueError('JWT subject is missing.')
        return UUID(subject)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, 'Invalid authentication token.')


def business_for(db: Session, user_id: UUID) -> Business:
    business = db.scalar(select(Business).where(Business.owner_id == user_id))
    if not business:
        raise HTTPException(409, 'Create your business profile first.')
    return business


def ensure_settings(db: Session, business: Business) -> BusinessSettings:
    if not business.settings:
        business.settings = BusinessSettings(business_id=business.id)
        db.add(business.settings)
        db.commit()
        db.refresh(business.settings)
    return business.settings


def money(v: Decimal | float | int) -> float:
    return round(float(v), 2)


def period_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days - 1)


def dashboard_payload(db: Session, business: Business) -> dict[str, Any]:
    st = ensure_settings(db, business)
    start = period_start(st.dashboard_period)
    sales = list(db.scalars(select(Sale).where(Sale.business_id == business.id, Sale.sale_date >= start)))
    expenses = list(db.scalars(select(Expense).where(Expense.business_id == business.id, Expense.expense_date >= start)))
    all_products = list(db.scalars(select(Product).where(Product.business_id == business.id)))
    products = [p for p in all_products if p.is_active]
    product_map = {p.id: p for p in all_products}
    revenue = sum((s.total_amount for s in sales), Decimal('0'))
    expense_total = sum((e.amount for e in expenses), Decimal('0'))
    cogs = sum((product_map[s.product_id].cost_price * s.quantity for s in sales if s.product_id in product_map), Decimal('0'))
    low_stock = [p for p in products if p.current_stock <= p.reorder_level]
    top = sorted(((p.name, sum(s.quantity for s in sales if s.product_id == p.id), sum((s.total_amount for s in sales if s.product_id == p.id), Decimal('0'))) for p in products), key=lambda x:(x[1],x[2]), reverse=True)[:5]
    channel_totals: dict[str, Decimal] = defaultdict(lambda: Decimal('0'))
    for s in sales: channel_totals[s.sales_channel] += s.total_amount
    best_channel = max(channel_totals.items(), key=lambda x:x[1])[0] if channel_totals else None
    revenue_trend = []
    expense_trend = []
    for i in range(st.dashboard_period):
        d = (start + timedelta(days=i)).date()
        revenue_trend.append({'date': d.isoformat(), 'value': money(sum((s.total_amount for s in sales if s.sale_date.date()==d), Decimal('0')))})
        expense_trend.append({'date': d.isoformat(), 'value': money(sum((e.amount for e in expenses if e.expense_date.date()==d), Decimal('0')))})
    recs = recommendations(db, business, sales, expenses, products, st)
    return {
        'overview': {'revenue':money(revenue),'expenses':money(expense_total),'estimated_profit':money(revenue-expense_total-cogs),'products':len(products),'sales_count':len(sales),'low_stock_count':len(low_stock),'best_selling_product':top[0][0] if top else None,'best_channel':best_channel},
        'trends': {'revenue': revenue_trend, 'expenses': expense_trend},
        'channels': [{'name':k,'value':money(v)} for k,v in sorted(channel_totals.items(), key=lambda x:x[1], reverse=True)],
        'top_products': [{'name':n,'quantity':q,'revenue':money(r)} for n,q,r in top],
        'low_stock': [{'id':str(p.id),'name':p.name,'stock':p.current_stock,'reorder_level':p.reorder_level} for p in sorted(low_stock,key=lambda p:p.current_stock)],
        'recommendations': recs,
        'period': st.dashboard_period,
        'currency': st.currency,
    }


def recommendations(db: Session, business: Business, sales: list[Sale], expenses: list[Expense], products: list[Product], st: BusinessSettings) -> list[dict[str,str]]:
    if not st.recommendations_enabled:
        return []
    now = datetime.now(timezone.utc)
    out: list[dict[str,str]] = []
    current = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    previous = (current - timedelta(days=1)).replace(day=1)
    cur_rev = sum((s.total_amount for s in sales if s.sale_date >= current), Decimal('0'))
    prev_rev = sum((s.total_amount for s in sales if previous <= s.sale_date < current), Decimal('0'))
    if st.sales_alerts and prev_rev:
        change = (cur_rev-prev_rev)/prev_rev*100
        if change > 0: out.append({'type':'positive','message':f'Sales are {money(abs(change))}% above the previous month.'})
        elif change < 0: out.append({'type':'warning','message':f'Sales are {money(abs(change))}% below the previous month. Review recent sales activity and pricing.'})
    if st.low_stock_alerts:
        out += [{'type':'warning','message':f'Restock {p.name}. {p.current_stock} units remain against a reorder level of {p.reorder_level}.'} for p in sorted(products,key=lambda p:p.current_stock) if p.current_stock <= p.reorder_level][:5]
    last_sale = {p.id:max((s.sale_date for s in sales if s.product_id==p.id), default=None) for p in products}
    out += [{'type':'info','message':f'{p.name} has no recorded sale in the last 30 days.'} for p in products if not last_sale[p.id] or last_sale[p.id] <= now-timedelta(days=30)][:5]
    if st.expense_alerts:
        cur_exp = sum((e.amount for e in expenses if e.expense_date>=current), Decimal('0'))
        prev_exp = sum((e.amount for e in expenses if previous<=e.expense_date<current), Decimal('0'))
        if prev_exp and cur_exp > prev_exp*Decimal('1.2'): out.append({'type':'warning','message':'Expenses are more than 20% above the previous month. Review the largest expense categories.'})
    if st.sales_alerts and sales:
        counts: dict[int,int] = defaultdict(int)
        for s in sales: counts[s.sale_date.weekday()] += 1
        busiest=max(counts.items(),key=lambda x:x[1])[0]
        out.append({'type':'info','message':f'{["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][busiest]} has the highest recorded sales activity in this period.'})
    if not out: out.append({'type':'info','message':'Keep recording sales and expenses to build a stronger decision history.'})
    return out[:10]


app = FastAPI(title='BizInsight API', version='2.0.0')

# CORS: allow explicitly configured stable origins plus only the BizInsight
# Vercel preview URL pattern. Do not use '*' with credentials.
_configured_origins = [
    origin.strip()
    for origin in settings.frontend_origin.split(',')
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_origins,
    allow_origin_regex=settings.frontend_origin_regex or None,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

@app.get('/api/health')
def health(db: Session = Depends(get_db)):
    db_ok = True
    try: db.execute(select(func.now()))
    except Exception: db_ok = False
    return {'status':'ok' if db_ok else 'degraded','database':db_ok,'ai_configured':bool(settings.deepseek_api_key)}

@app.get('/api/business', response_model=BusinessOut)
def get_business(user_id: UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    b = db.scalar(select(Business).where(Business.owner_id==user_id))
    if not b: raise HTTPException(404,'Business profile not found.')
    return b

@app.post('/api/business', response_model=BusinessOut)
def create_business(payload: BusinessIn, user_id: UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    existing = db.scalar(select(Business).where(Business.owner_id==user_id))
    if existing: raise HTTPException(409,'Business profile already exists.')
    b=Business(owner_id=user_id, **payload.model_dump())
    b.settings=BusinessSettings()
    db.add(b); db.commit(); db.refresh(b); return b

@app.put('/api/business', response_model=BusinessOut)
def update_business(payload: BusinessIn, user_id: UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    b=business_for(db,user_id)
    for k,v in payload.model_dump().items(): setattr(b,k,v)
    db.commit(); db.refresh(b); return b

@app.get('/api/settings')
def get_settings(user_id: UUID=Depends(current_user_id), db: Session=Depends(get_db)):
    return ensure_settings(db,business_for(db,user_id))

@app.put('/api/settings')
def update_settings(payload: SettingsIn, user_id: UUID=Depends(current_user_id), db: Session=Depends(get_db)):
    st=ensure_settings(db,business_for(db,user_id))
    for k,v in payload.model_dump().items(): setattr(st,k,v)
    db.commit(); db.refresh(st); return st

@app.get('/api/categories')
def list_categories(user_id: UUID=Depends(current_user_id), db: Session=Depends(get_db)):
    b=business_for(db,user_id); return list(db.scalars(select(Category).where(Category.business_id==b.id).order_by(Category.name)))

@app.post('/api/categories')
def create_category(payload: CategoryIn,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); c=Category(business_id=b.id,**payload.model_dump()); db.add(c); db.commit(); db.refresh(c); return c

@app.delete('/api/categories/{category_id}')
def delete_category(category_id:UUID,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); c=db.scalar(select(Category).where(Category.id==category_id,Category.business_id==b.id))
    if not c: raise HTTPException(404,'Category not found.')
    if db.scalar(select(Product).where(Product.category_id==c.id)): raise HTTPException(409,'Category still has products.')
    db.delete(c); db.commit(); return {'ok':True}

@app.get('/api/products')
def list_products(user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); cats={c.id:c.name for c in db.scalars(select(Category).where(Category.business_id==b.id))}; ps=list(db.scalars(select(Product).where(Product.business_id==b.id).order_by(Product.name)))
    return [{**{k:getattr(p,k) for k in ['id','name','description','cost_price','selling_price','current_stock','reorder_level','sku','is_active','created_at']},'id':str(p.id),'category_id':str(p.category_id),'category_name':cats.get(p.category_id)} for p in ps]

@app.post('/api/products')
def create_product(payload:ProductIn,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id)
    if not db.scalar(select(Category).where(Category.id==payload.category_id,Category.business_id==b.id)): raise HTTPException(400,'Invalid category.')
    p=Product(business_id=b.id,**payload.model_dump()); db.add(p); db.commit(); db.refresh(p); return p

@app.put('/api/products/{product_id}')
def update_product(product_id:UUID,payload:ProductIn,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); p=db.scalar(select(Product).where(Product.id==product_id,Product.business_id==b.id))
    if not p: raise HTTPException(404,'Product not found.')
    if not db.scalar(select(Category).where(Category.id==payload.category_id,Category.business_id==b.id)): raise HTTPException(400,'Invalid category.')
    for k,v in payload.model_dump().items(): setattr(p,k,v)
    db.commit(); db.refresh(p); return p

@app.delete('/api/products/{product_id}')
def delete_product(product_id:UUID,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); p=db.scalar(select(Product).where(Product.id==product_id,Product.business_id==b.id))
    if not p: raise HTTPException(404,'Product not found.')
    if db.scalar(select(Sale).where(Sale.product_id==p.id)): p.is_active=False
    else: db.delete(p)
    db.commit(); return {'ok':True}

@app.get('/api/sales')
def list_sales(user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db),limit:int=Query(100,le=500)):
    b=business_for(db,user_id); rows=db.execute(select(Sale,Product.name).join(Product,Product.id==Sale.product_id).where(Sale.business_id==b.id).order_by(Sale.sale_date.desc()).limit(limit)).all()
    return [{'id':str(s.id),'product_id':str(s.product_id),'product_name':name,'quantity':s.quantity,'unit_price':money(s.unit_price),'total_amount':money(s.total_amount),'sales_channel':s.sales_channel,'payment_method':s.payment_method,'sale_date':s.sale_date.isoformat()} for s,name in rows]

@app.post('/api/sales')
def create_sale(payload:SaleIn,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); p=db.scalar(select(Product).where(Product.id==payload.product_id,Product.business_id==b.id).with_for_update())
    if not p or not p.is_active: raise HTTPException(404,'Product not found.')
    if payload.quantity>p.current_stock: raise HTTPException(400,f'Only {p.current_stock} units are available.')
    unit=payload.unit_price if payload.unit_price is not None else p.selling_price
    s=Sale(business_id=b.id,product_id=p.id,quantity=payload.quantity,unit_price=unit,total_amount=unit*payload.quantity,sales_channel=payload.sales_channel,payment_method=payload.payment_method,sale_date=payload.sale_date or datetime.now(timezone.utc))
    p.current_stock-=payload.quantity; db.add(s); db.commit(); db.refresh(s); return s

@app.delete('/api/sales/{sale_id}')
def delete_sale(sale_id:UUID,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); s=db.scalar(select(Sale).where(Sale.id==sale_id,Sale.business_id==b.id))
    if not s: raise HTTPException(404,'Sale not found.')
    p=db.scalar(select(Product).where(Product.id==s.product_id,Product.business_id==b.id).with_for_update());
    if p: p.current_stock+=s.quantity
    db.delete(s); db.commit(); return {'ok':True}

@app.get('/api/expenses')
def list_expenses(user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db),limit:int=Query(100,le=500)):
    b=business_for(db,user_id); es=list(db.scalars(select(Expense).where(Expense.business_id==b.id).order_by(Expense.expense_date.desc()).limit(limit))); return [{**{k:getattr(e,k) for k in ['id','name','category','amount','notes']},'id':str(e.id),'amount':money(e.amount),'expense_date':e.expense_date.isoformat()} for e in es]

@app.post('/api/expenses')
def create_expense(payload:ExpenseIn,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); e=Expense(business_id=b.id,**payload.model_dump(exclude={'expense_date'}),expense_date=payload.expense_date or datetime.now(timezone.utc)); db.add(e); db.commit(); db.refresh(e); return e

@app.delete('/api/expenses/{expense_id}')
def delete_expense(expense_id:UUID,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); e=db.scalar(select(Expense).where(Expense.id==expense_id,Expense.business_id==b.id));
    if not e: raise HTTPException(404,'Expense not found.')
    db.delete(e); db.commit(); return {'ok':True}

@app.get('/api/dashboard')
def dashboard(user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)): return dashboard_payload(db,business_for(db,user_id))

@app.get('/api/reports/summary')
def report_summary(user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); d=dashboard_payload(db,b); return d

@app.get('/api/reports/export/{kind}')
def export_report(kind:str,user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); out=io.StringIO(); w=csv.writer(out)
    if kind=='sales':
        w.writerow(['date','product_id','quantity','unit_price','total_amount','channel','payment_method'])
        for s in db.scalars(select(Sale).where(Sale.business_id==b.id).order_by(Sale.sale_date)): w.writerow([s.sale_date.isoformat(),s.product_id,s.quantity,s.unit_price,s.total_amount,s.sales_channel,s.payment_method])
    elif kind=='expenses':
        w.writerow(['date','name','category','amount','notes'])
        for e in db.scalars(select(Expense).where(Expense.business_id==b.id).order_by(Expense.expense_date)): w.writerow([e.expense_date.isoformat(),e.name,e.category,e.amount,e.notes or ''])
    elif kind=='inventory':
        w.writerow(['name','sku','stock','reorder_level','cost_price','selling_price'])
        for p in db.scalars(select(Product).where(Product.business_id==b.id).order_by(Product.name)): w.writerow([p.name,p.sku or '',p.current_stock,p.reorder_level,p.cost_price,p.selling_price])
    else: raise HTTPException(404,'Unknown report.')
    from fastapi.responses import StreamingResponse
    return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="bizinsight-{kind}.csv"'})

@app.get('/api/reports/export/summary/pdf')
def export_summary_pdf(user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); d=dashboard_payload(db,b)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        raise HTTPException(500,'PDF export is not available because reportlab is not installed.')
    from fastapi.responses import StreamingResponse
    buf=io.BytesIO()
    c=canvas.Canvas(buf,pagesize=A4)
    width,height=A4
    y=height-54
    c.setFont('Helvetica-Bold',18); c.drawString(48,y,'BizInsight Summary Report'); y-=28
    c.setFont('Helvetica',10); c.drawString(48,y,f'Business: {b.name}'); y-=16
    c.drawString(48,y,f'Period: Last {d["period"]} days'); y-=28
    c.setFont('Helvetica-Bold',11); c.drawString(48,y,'Overview'); y-=18
    c.setFont('Helvetica',10)
    for label,key in [('Revenue','revenue'),('Expenses','expenses'),('Estimated profit','estimated_profit'),('Sales count','sales_count'),('Low-stock products','low_stock_count')]:
        c.drawString(60,y,f'{label}: {d["overview"][key]}'); y-=15
    y-=10; c.setFont('Helvetica-Bold',11); c.drawString(48,y,'Decision-support findings'); y-=18; c.setFont('Helvetica',10)
    for rec in d['recommendations'][:10]:
        text=rec['message'];
        while text:
            chunk=text[:105];
            if len(text)>105: chunk=chunk.rsplit(' ',1)[0]
            c.drawString(60,y,'- '+chunk); y-=14; text=text[len(chunk):].lstrip()
            if y<55: c.showPage(); y=height-54; c.setFont('Helvetica',10)
    c.showPage(); c.save(); buf.seek(0)
    return StreamingResponse(buf,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="bizinsight-summary-{datetime.now(timezone.utc):%Y%m%d}.pdf"'})

@app.post('/api/imports/{kind}')
def import_csv(kind:str,file:UploadFile=File(...),user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    if kind not in {'sales','expenses','products'}: raise HTTPException(404,'Unsupported import type.')
    b=business_for(db,user_id)
    raw=file.file.read()
    if len(raw) > 5 * 1024 * 1024: raise HTTPException(413,'CSV file is too large. Maximum size is 5 MB.')
    try: rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    except UnicodeDecodeError: raise HTTPException(400,'CSV must be UTF-8 encoded.')
    if not rows: raise HTTPException(400,'CSV contains no rows.')
    if len(rows) > 5000: raise HTTPException(413,'CSV contains too many rows. Maximum is 5,000.')
    errors=[]; imported=0
    try:
        for i,row in enumerate(rows, start=2):
            try:
                if kind=='products':
                    cat_name=(row.get('category') or 'General').strip()
                    if not cat_name:
                        raise ValueError('category is required')
                    cat=db.scalar(select(Category).where(Category.business_id==b.id,func.lower(Category.name)==cat_name.lower()))
                    if not cat:
                        if len(cat_name) > 120:
                            raise ValueError('category must be at most 120 characters')
                        cat=Category(business_id=b.id,name=cat_name); db.add(cat); db.flush()
                    product=ProductIn(
                        category_id=cat.id,
                        name=(row.get('name') or '').strip(),
                        description=row.get('description') or None,
                        cost_price=Decimal(row.get('cost_price','0') or '0'),
                        selling_price=Decimal(row.get('selling_price','0') or '0'),
                        current_stock=int(row.get('current_stock','0') or '0'),
                        reorder_level=int(row.get('reorder_level','5') or '5'),
                        sku=row.get('sku') or None,
                    )
                    db.add(Product(business_id=b.id, **product.model_dump()))
                elif kind=='expenses':
                    expense=ExpenseIn(
                        name=(row.get('name') or '').strip(),
                        category=(row.get('category') or '').strip(),
                        amount=Decimal(row.get('amount') or '0'),
                        expense_date=datetime.fromisoformat(row['date']),
                        notes=row.get('notes') or None,
                    )
                    db.add(Expense(business_id=b.id, **expense.model_dump()))
                else:
                    p=db.scalar(select(Product).where(Product.business_id==b.id,Product.id==UUID(row['product_id'])).with_for_update())
                    if not p or not p.is_active:
                        raise ValueError('product_id not found')
                    sale=SaleIn(
                        product_id=p.id,
                        quantity=int(row['quantity']),
                        unit_price=Decimal(row['unit_price']) if row.get('unit_price') else p.selling_price,
                        sales_channel=(row.get('channel') or 'Physical Store').strip(),
                        payment_method=(row.get('payment_method') or 'Cash').strip(),
                        sale_date=datetime.fromisoformat(row['date']),
                    )
                    if sale.quantity > p.current_stock:
                        raise ValueError('quantity exceeds stock')
                    p.current_stock-=sale.quantity
                    db.add(Sale(business_id=b.id, total_amount=sale.unit_price * sale.quantity, **sale.model_dump()))
                imported+=1
            except Exception as ex: errors.append({'row':i,'error':str(ex)})
        if errors: db.rollback(); raise HTTPException(422,{'message':'Import rolled back because validation failed.','errors':errors[:20]})
        db.commit()
    except HTTPException: raise
    except Exception: db.rollback(); raise
    return {'imported':imported,'errors':[]}

@app.post('/api/ai/insights',response_model=InsightOut)
def ai_insights(user_id:UUID=Depends(current_user_id),db:Session=Depends(get_db)):
    b=business_for(db,user_id); st=ensure_settings(db,b)
    if not st.ai_enabled: return InsightOut(available=False,summary='AI insights are disabled in Settings.',key_findings=[],positive_signals=[],attention_items=[],recommendations=[],generated_at=datetime.now(timezone.utc))
    data=dashboard_payload(db,b)
    if not settings.deepseek_api_key:
        rec=[x['message'] for x in data['recommendations']]
        return InsightOut(available=False,summary='DeepSeek is not configured. The deterministic DSS findings remain available.',key_findings=rec[:5],positive_signals=[],attention_items=rec[:5],recommendations=rec[:5],generated_at=datetime.now(timezone.utc))
    system='''You are the interpretation layer for a small-business decision support system. Use ONLY the supplied analytics. Do not invent values, products, dates, causes, forecasts, or facts. Do not claim certainty beyond the data. The deterministic analytics are the source of truth. Return JSON with keys: summary (string), key_findings (array of strings), positive_signals (array), attention_items (array), recommendations (array). Recommendations must be practical and clearly framed as suggestions for the business owner, not decisions.'''
    prompt=json.dumps({'business':b.name,'currency':st.currency,'analytics':data},default=str)
    try:
        r=httpx.post(f'{settings.deepseek_base_url.rstrip("/")}/chat/completions',headers={'Authorization':f'Bearer {settings.deepseek_api_key}','Content-Type':'application/json'},json={'model':settings.deepseek_model,'temperature':0.2,'messages':[{'role':'system','content':system},{'role':'user','content':prompt}], 'response_format':{'type':'json_object'}},timeout=30)
        r.raise_for_status(); content=r.json()['choices'][0]['message']['content']; parsed=json.loads(content)
        result=InsightOut(available=True,generated_at=datetime.now(timezone.utc),**{k:parsed.get(k,[]) if k!='summary' else parsed.get(k,'') for k in ['summary','key_findings','positive_signals','attention_items','recommendations']})
        db.add(AiInsightRun(business_id=b.id,status='success',response_json=result.model_dump(mode='json'))); db.commit(); return result
    except Exception:
        rec=[x['message'] for x in data['recommendations']]
        result=InsightOut(available=False,summary='DeepSeek was unavailable, so the system returned the deterministic decision-support findings instead.',key_findings=rec[:5],positive_signals=[],attention_items=rec[:5],recommendations=rec[:5],generated_at=datetime.now(timezone.utc))
        db.add(AiInsightRun(business_id=b.id,status='fallback',response_json=result.model_dump(mode='json'))); db.commit(); return result
