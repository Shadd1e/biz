from datetime import date
from app.analytics import calculate

def test_empty():
    x=calculate([],[],[],30)
    assert x['overview']['revenue']==0
    assert x['overview']['gross_profit'] is None
    assert x['overview']['expense_ratio'] is None

def test_missing_cost_not_zero():
    sale={'sale_date':date.today().isoformat(),'total_amount':'120.00','unit_cost_at_sale':None,'quantity':2,'product_name':'A'}
    x=calculate([sale],[],[],30)
    assert x['overview']['gross_profit'] is None

def test_known_cost():
    sale={'sale_date':date.today().isoformat(),'total_amount':'120.00','unit_cost_at_sale':'25.00','quantity':2,'product_name':'A'}
    expense={'expense_date':date.today().isoformat(),'amount':'30.00'}
    x=calculate([sale],[expense],[],30)
    assert x['overview']['gross_profit']==70
    assert x['overview']['expense_ratio']==25
