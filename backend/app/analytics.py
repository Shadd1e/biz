from decimal import Decimal
from datetime import date, timedelta
from collections import defaultdict

def D(v): return Decimal(str(v if v is not None else 0))
def calculate(sales, expenses, products, days=30):
    start=date.today()-timedelta(days=days-1)
    def valid(row, key): return date.fromisoformat(str(row[key])[:10])>=start
    ss=[s for s in sales if valid(s,'sale_date')]
    ee=[e for e in expenses if valid(e,'expense_date')]
    revenue=sum((D(s['total_amount']) for s in ss),Decimal(0))
    expense=sum((D(e['amount']) for e in ee),Decimal(0))
    # Historical unit costs are captured at the time of sale; missing costs remain unknown.
    known_costs=bool(ss) and all(s.get('unit_cost_at_sale') is not None for s in ss)
    cogs=sum((D(s['unit_cost_at_sale'])*int(s['quantity']) for s in ss),Decimal(0)) if known_costs else None
    gross_profit=revenue-cogs if cogs is not None else None
    by_day=defaultdict(lambda: {'revenue':Decimal(0),'expenses':Decimal(0)})
    channels=defaultdict(Decimal); quantities=defaultdict(int)
    for s in ss:
        day=str(s['sale_date'])[:10]; by_day[day]['revenue']+=D(s['total_amount'])
        channels[s.get('sales_channel') or 'Other']+=D(s['total_amount'])
        quantities[s.get('product_name') or 'Unknown']+=int(s['quantity'])
    for e in ee: by_day[str(e['expense_date'])[:10]]['expenses']+=D(e['amount'])
    dates=[(start+timedelta(days=i)).isoformat() for i in range(days)]
    low=[p for p in products if p.get('is_active',True) and int(p['current_stock'])<=int(p['reorder_level'])]
    notes=[]
    if not ss: notes.append({'type':'info','message':'No recorded sales in this period. Add sales to begin analysis.'})
    if low: notes.append({'type':'warning','message':f'{len(low)} product(s) have reached their reorder threshold.'})
    if revenue>0 and expense/revenue>=Decimal('0.8'): notes.append({'type':'warning','message':'Recorded operating expenses equal at least 80% of sales. Review the expense breakdown.'})
    
    if gross_profit is None: notes.append({'type':'info','message':'Gross profit is unavailable because at least one sale lacks its sale-time cost. Update the database migration and review historical costs before relying on this figure.'})
    return {'overview':{'revenue':float(revenue),'expenses':float(expense),'estimated_profit':float(gross_profit) if gross_profit is not None else None,'gross_profit':float(gross_profit) if gross_profit is not None else None,'sales_count':len(ss),'low_stock_count':len(low),'expense_ratio':round(float(expense/revenue*100),2) if revenue>0 else None},'trends':{'revenue':[{'date':day,'value':float(by_day[day]['revenue'])} for day in dates],'expenses':[{'date':day,'value':float(by_day[day]['expenses'])} for day in dates]},'channels':[{'name':k,'value':float(v)} for k,v in channels.items()],'top_products':[{'name':k,'quantity':v} for k,v in sorted(quantities.items(),key=lambda x:-x[1])[:5]],'recommendations':notes,'period':days,'limitations':['Gross profit requires sale-time cost information for every sale in the selected period. Missing historical costs are not silently treated as zero.']}
