"""BizInsight DSS API. Every query is scoped to the authenticated owner's business."""
import os, csv, io, json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from contextlib import contextmanager
from collections import defaultdict
import httpx
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Query
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import BaseModel, Field
from .analytics import calculate, D

app=FastAPI(title='BizInsight DSS API',version='1.0.0')
origins=[x.strip() for x in os.getenv('FRONTEND_ORIGIN','http://localhost:5173').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST','PUT','DELETE','OPTIONS'],allow_headers=['Authorization','Content-Type'],allow_credentials=True)
url=os.getenv('DATABASE_URL','').replace('postgresql://','postgresql+psycopg://',1)
engine=create_engine(url,pool_pre_ping=True) if url else None

@app.get('/health')
def health(): return {'status':'ok','service':'bizinsight-api','database_configured':bool(engine)}

async def owner(authorization:str|None=Header(None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Sign in required')
    base=os.getenv('SUPABASE_URL','').rstrip('/')
    anon=os.getenv('SUPABASE_ANON_KEY','')
    if not base or not anon: raise HTTPException(503,'Authentication is not configured')
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r=await client.get(f'{base}/auth/v1/user',headers={'apikey':anon,'Authorization':authorization})
        if r.status_code!=200: raise HTTPException(401,'Session expired or invalid')
        return str(UUID(r.json()['id']))
    except HTTPException: raise
    except Exception: raise HTTPException(503,'Unable to verify session')

@contextmanager
def db():
    if engine is None: raise HTTPException(503,'DATABASE_URL is not configured')
    with engine.begin() as c: yield c

def allrows(c,query,params=None): return [dict(x) for x in c.execute(text(query),params or {}).mappings().all()]
def onerow(c,query,params=None):
    r=c.execute(text(query),params or {}).mappings().first(); return dict(r) if r else None

def business(c,uid,required=True):
    b=onerow(c,'select * from businesses where owner_id=:uid',{'uid':uid})
    if required and not b: raise HTTPException(404,'Set up your business first')
    return b

def own(c,uid,table,rid):
    b=business(c,uid)
    row=onerow(c,f'select * from {table} where id=:id and business_id=:bid',{'id':rid,'bid':b['id']})
    if not row: raise HTTPException(404,'Record not found')
    return b,row

def insert(c,table,data):
    cols=list(data)
    sql=f'insert into {table} ({",".join(cols)}) values ({",".join(":"+k for k in cols)}) returning *'
    return onerow(c,sql,data)

def update(c,table,rid,bid,data):
    cols=list(data)
    if not cols: raise HTTPException(400,'Nothing to update')
    sql=f'update {table} set '+','.join(f'{k}=:{k}' for k in cols)+' where id=:rid and business_id=:bid returning *'
    return onerow(c,sql,{**data,'rid':rid,'bid':bid})

def clean(row):
    return json.loads(json.dumps(row,default=lambda x: x.isoformat() if hasattr(x,'isoformat') else str(x)))

def safe(data,allowed): return {k:v for k,v in data.items() if k in allowed}

BUS_FIELDS={'name','business_type','description','phone','email','address'}
SET_FIELDS={'currency','dashboard_period','recommendations_enabled','ai_enabled','low_stock_alerts','expense_alerts','sales_alerts','theme'}
FIELDS={'categories':{'name','description'},'products':{'name','category_id','cost_price','selling_price','current_stock','reorder_level','sku','description','is_active'},'expenses':{'name','category','amount','notes','expense_date'}}

@app.get('/api/business')
def get_business(uid=Depends(owner)):
    with db() as c: return clean(business(c,uid,False))

@app.post('/api/business')
def create_business(payload:dict,uid=Depends(owner)):
    data=safe(payload,BUS_FIELDS)
    if not str(data.get('name','')).strip(): raise HTTPException(422,'Business name is required')
    with db() as c:
        if business(c,uid,False): raise HTTPException(409,'Business already exists')
        b=insert(c,'businesses',{'owner_id':uid,**data})
        insert(c,'business_settings',{'business_id':b['id']})
        return clean(b)

@app.put('/api/business')
def edit_business(payload:dict,uid=Depends(owner)):
    data=safe(payload,BUS_FIELDS)
    if not str(data.get('name','')).strip(): raise HTTPException(422,'Business name is required')
    with db() as c:
        b=business(c,uid)
        return clean(update(c,'businesses',b['id'],b['id'],data) if False else onerow(c,'update businesses set name=:name,business_type=:business_type,description=:description,phone=:phone,email=:email,address=:address where id=:bid and owner_id=:uid returning *',{**{k:data.get(k,b.get(k)) for k in BUS_FIELDS},'bid':b['id'],'uid':uid}))

@app.get('/api/settings')
def get_settings(uid=Depends(owner)):
    with db() as c:
        b=business(c,uid)
        s=onerow(c,'select * from business_settings where business_id=:bid',{'bid':b['id']})
        return clean(s)

@app.put('/api/settings')
def edit_settings(payload:dict,uid=Depends(owner)):
    data=safe(payload,SET_FIELDS)
    with db() as c:
        b=business(c,uid)
        return clean(update(c,'business_settings',(onerow(c,'select id from business_settings where business_id=:bid',{'bid':b['id']}) or {})['id'],b['id'],data))

@app.get('/api/dashboard')
def dashboard(uid=Depends(owner)):
    with db() as c: return summary(c,business(c,uid))

@app.get('/api/{table}')
def list_records(table:str,uid=Depends(owner)):
    if table not in FIELDS and table!='sales': raise HTTPException(404,'Unknown resource')
    with db() as c:
        b=business(c,uid)
        if table=='products': q='select p.*,c.name category_name from products p left join categories c on c.id=p.category_id where p.business_id=:bid order by p.created_at desc'
        elif table=='sales': q='select s.*,p.name product_name from sales s left join products p on p.id=s.product_id where s.business_id=:bid order by s.sale_date desc limit 2000'
        else: q=f'select * from {table} where business_id=:bid order by created_at desc limit 2000'
        return clean(allrows(c,q,{'bid':b['id']}))

@app.post('/api/{table}')
def add_record(table:str,payload:dict,uid=Depends(owner)):
    if table not in FIELDS and table!='sales': raise HTTPException(404,'Unknown resource')
    with db() as c:
        b=business(c,uid)
        if table=='sales':
            pid=payload.get('product_id');qty=int(payload.get('quantity',0))
            if qty<=0: raise HTTPException(422,'Quantity must be positive')
            p=onerow(c,'select * from products where id=:id and business_id=:bid for update',{'id':pid,'bid':b['id']})
            if not p: raise HTTPException(422,'Product does not belong to your business')
            if p['current_stock']<qty: raise HTTPException(422,'Insufficient stock')
            price=D(payload.get('unit_price',p['selling_price']))
            if price<0: raise HTTPException(422,'Invalid price')
            data={'product_id':pid,'quantity':qty,'unit_price':price,'total_amount':price*qty,'unit_cost_at_sale':p['cost_price'],'sales_channel':payload.get('sales_channel','Physical Store'),'payment_method':payload.get('payment_method','Cash'),'sale_date':payload.get('sale_date') or datetime.utcnow().isoformat(),'business_id':b['id']}
            c.execute(text('update products set current_stock=current_stock-:qty where id=:pid and business_id=:bid'),{'qty':qty,'pid':pid,'bid':b['id']})
        else:
            data=safe(payload,FIELDS[table]);data['business_id']=b['id']
            if table=='products':
                cat=onerow(c,'select id from categories where id=:id and business_id=:bid',{'id':data.get('category_id'),'bid':b['id']})
                if not cat: raise HTTPException(422,'Choose a category belonging to your business')
        try: return clean(insert(c,table,data))
        except IntegrityError: raise HTTPException(422,'Record violates a database constraint')

@app.put('/api/{table}/{rid}')
def edit_record(table:str,rid:UUID,payload:dict,uid=Depends(owner)):
    if table not in FIELDS: raise HTTPException(405,'Editing this resource is not supported')
    with db() as c:
        b,_=own(c,uid,table,str(rid))
        data=safe(payload,FIELDS[table]);
        if table=='products' and 'category_id' in data:
            if not onerow(c,'select id from categories where id=:id and business_id=:bid',{'id':data['category_id'],'bid':b['id']}): raise HTTPException(422,'Invalid category')
        return clean(update(c,table,str(rid),b['id'],data))

@app.delete('/api/{table}/{rid}',status_code=204)
def delete_record(table:str,rid:UUID,uid=Depends(owner)):
    if table not in FIELDS and table!='sales': raise HTTPException(404,'Unknown resource')
    with db() as c:
        b,row=own(c,uid,table,str(rid))
        if table=='sales':
            c.execute(text('update products set current_stock=current_stock+:q where id=:id and business_id=:bid'),{'q':row['quantity'],'id':row['product_id'],'bid':b['id']})
        c.execute(text(f'delete from {table} where id=:rid and business_id=:bid'),{'rid':rid,'bid':b['id']})
    return Response(status_code=204)

def summary(c,b):
    bid=b['id']; s=onerow(c,'select * from business_settings where business_id=:bid',{'bid':bid}) or {}
    sales=allrows(c,'select s.*,p.name product_name from sales s left join products p on p.id=s.product_id where s.business_id=:bid',{'bid':bid})
    expenses=allrows(c,'select * from expenses where business_id=:bid',{'bid':bid})
    products=allrows(c,'select * from products where business_id=:bid',{'bid':bid})
    d=calculate(sales,expenses,products,int(s.get('dashboard_period') or 30));d['currency']=s.get('currency') or 'NGN'
    return d

@app.get('/api/reports/summary')
def report(uid=Depends(owner)):
    with db() as c: return summary(c,business(c,uid))

@app.get('/api/reports/export/{kind}')
def export(kind:str,uid=Depends(owner)):
    if kind not in {'sales','expenses','inventory'}: raise HTTPException(404,'Unknown export')
    table='products' if kind=='inventory' else kind
    with db() as c:
        b=business(c,uid)
        rows=allrows(c,f'select * from {table} where business_id=:bid order by created_at desc limit 10000',{'bid':b['id']})
    fields={'sales':['sale_date','product_id','quantity','unit_price','total_amount','sales_channel','payment_method'],'expenses':['expense_date','name','category','amount','notes'],'inventory':['name','sku','category_id','selling_price','cost_price','current_stock','reorder_level']}[kind]
    stream=io.StringIO();w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
    for row in rows:
        # Avoid formula injection in spreadsheet applications.
        w.writerow({k:("'"+str(row.get(k)) if isinstance(row.get(k),str) and row[k].startswith(('=','+','-','@')) else row.get(k,'')) for k in fields})
    return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="bizinsight-{kind}.csv"'})

@app.post('/api/imports/{kind}')
async def import_csv(kind:str,file:UploadFile=File(...),uid=Depends(owner)):
    if kind not in {'sales','expenses','products'}: raise HTTPException(404,'Unknown import')
    raw=await file.read(1_000_001)
    if len(raw)>1_000_000: raise HTTPException(413,'CSV must be at most 1 MB')
    try: data=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    except (UnicodeDecodeError,csv.Error): raise HTTPException(422,'Invalid UTF-8 CSV')
    if len(data)>2000: raise HTTPException(413,'Maximum 2000 rows per import')
    required={'sales':{'product_id','quantity','unit_price','sale_date'},'expenses':{'name','category','amount','expense_date'},'products':{'name','category_id','selling_price','current_stock'}}[kind]
    if not data or not required.issubset(data[0]): raise HTTPException(422,f'CSV requires columns: {", ".join(sorted(required))}')
    errors=[];rows=[]
    for n,row in enumerate(data,2):
        try:
            if kind=='sales':
                obj={'product_id':str(UUID(row['product_id'])),'quantity':int(row['quantity']),'unit_price':D(row['unit_price']),'sale_date':datetime.fromisoformat(row['sale_date'])}
                if obj['quantity']<=0 or obj['unit_price']<0: raise ValueError('Invalid quantity or price')
            elif kind=='expenses':
                obj={'name':row['name'].strip(),'category':row['category'].strip(),'amount':D(row['amount']),'expense_date':datetime.fromisoformat(row['expense_date'])}
                if not obj['name'] or not obj['category'] or obj['amount']<=0: raise ValueError('Invalid expense')
            else:
                obj={'name':row['name'].strip(),'category_id':str(UUID(row['category_id'])),'selling_price':D(row['selling_price']),'cost_price':D(row['cost_price']) if row.get('cost_price') else None,'current_stock':int(row['current_stock']),'reorder_level':int(row.get('reorder_level') or 5)}
                if not obj['name'] or obj['selling_price']<0 or obj['current_stock']<0: raise ValueError('Invalid product')
            rows.append(obj)
        except (ValueError,TypeError,KeyError) as exc: errors.append({'row':n,'error':str(exc)[:150]})
    if errors: raise HTTPException(422,{'message':'Import rejected; no rows saved','errors':errors[:100]})
    with db() as c:
        b=business(c,uid)
        for obj in rows:
            if kind=='sales':
                p=onerow(c,'select * from products where id=:id and business_id=:bid for update',{'id':obj['product_id'],'bid':b['id']})
                if not p or p['current_stock']<obj['quantity']: raise HTTPException(422,'Invalid product or insufficient stock; batch rolled back')
                obj['total_amount']=obj['unit_price']*obj['quantity'];obj['unit_cost_at_sale']=p['cost_price']
                c.execute(text('update products set current_stock=current_stock-:q where id=:id'),{'q':obj['quantity'],'id':obj['product_id']})
            elif kind=='products':
                if not onerow(c,'select id from categories where id=:id and business_id=:bid',{'id':obj['category_id'],'bid':b['id']}): raise HTTPException(422,'Invalid category; batch rolled back')
            obj['business_id']=b['id'];insert(c,kind,obj)
    return {'imported':len(rows),'rejected':0,'duplicate_policy':'Append only; do not retry the same file without checking existing records.'}

@app.post('/api/ai/insights')
async def ai_insights(uid=Depends(owner)):
    with db() as c:
        b=business(c,uid)
        settings=onerow(c,'select * from business_settings where business_id=:bid',{'bid':b['id']}) or {}
        if not settings.get('ai_enabled',True):
            raise HTTPException(403,'AI insights are disabled in Settings. Enable DeepSeek interpretation to use this feature.')
        d=summary(c,b)
    findings=[r['message'] for r in d['recommendations']]
    fallback={'available':False,'summary':'This summary is based on recorded business data. Gross profit is not available without reliable historical costs.','key_findings':findings,'positive_signals':[],'attention_items':findings,'recommendations':['Review your recorded sales and expenses.']}
    key=os.getenv('DEEPSEEK_API_KEY','')
    if not key: return fallback
    try:
        prompt=json.dumps({'overview':d['overview'],'period':d['period'],'rule_based_findings':findings})
        async with httpx.AsyncClient(timeout=12) as client:
            r=await client.post(os.getenv('DEEPSEEK_BASE_URL','https://api.deepseek.com').rstrip('/')+'/chat/completions',headers={'Authorization':f'Bearer {key}'},json={'model':'deepseek-chat','messages':[{'role':'system','content':'Explain provided metrics only. Do not invent figures. Return a short plain-text summary.'},{'role':'user','content':prompt}],'max_tokens':350})
        r.raise_for_status();message=r.json()['choices'][0]['message']['content']
        if not isinstance(message,str) or len(message)>4000: return fallback
        return {**fallback,'available':True,'summary':message}
    except Exception: return fallback
