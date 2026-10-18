from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_is_available_without_database_credentials():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'

def test_static_dashboard_routes_precede_dynamic_resource_route():
    paths = [getattr(route, 'path', '') for route in app.routes]
    dashboard_index = paths.index('/api/dashboard')
    dynamic_index = paths.index('/api/{table}')
    assert dashboard_index < dynamic_index
    assert paths.index('/api/reports/summary') < dynamic_index

def test_summary_pdf_export_route_is_registered():
    assert '/api/reports/export/summary/pdf' in [getattr(route, 'path', '') for route in app.routes]
