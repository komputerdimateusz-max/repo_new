from fastapi.testclient import TestClient

from app.main import app, startup
from app.db.session import SessionLocal
from app.models import RestaurantSetting, User
from app.core.security import get_password_hash

startup()
client = TestClient(app)


def allow_orders_now() -> None:
    with SessionLocal() as db:
        settings = db.get(RestaurantSetting, 1)
        settings.cut_off_time = "23:59"
        db.commit()


def ensure_customer_user() -> None:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "customer1").first()
        if user is None:
            db.add(User(username="customer1", password_hash=get_password_hash("pass123"), role="CUSTOMER", is_active=True))
            db.commit()


def login_customer() -> None:
    ensure_customer_user()
    response = client.post('/login', data={'username': 'customer1', 'password': 'pass123'}, follow_redirects=False)
    assert response.status_code == 303


def login_admin() -> None:
    response = client.post('/login', data={'username': 'admin', 'password': '123'}, follow_redirects=False)
    assert response.status_code == 303


def test_root_requires_login() -> None:
    anonymous = TestClient(app)
    response = anonymous.get('/', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/login'


def test_me_update_and_order_flow() -> None:
    allow_orders_now()
    login_customer()
    me = client.get('/api/v1/me')
    assert me.status_code == 200

    companies = client.get('/api/v1/companies').json()
    company_id = companies[0]['id']
    updated = client.patch('/api/v1/me', json={'name': 'Pilot User', 'postal_code': '66-400', 'company_id': company_id})
    assert updated.status_code == 200

    menu = client.get('/api/v1/menu/today').json()
    first_item_id = menu['items'][0]['id']
    order = client.post('/api/v1/orders', json={'payment_method': 'BLIK', 'items': [{'menu_item_id': first_item_id, 'qty': 1}]})
    assert order.status_code == 200


def test_admin_settings_requires_session_auth_and_csv_export() -> None:
    noauth = TestClient(app).get('/api/v1/admin/settings')
    assert noauth.status_code == 401

    login_admin()
    settings_response = client.get('/api/v1/admin/settings')
    assert settings_response.status_code == 200

    export = client.get('/api/v1/admin/orders/today.csv')
    assert export.status_code == 200
    assert export.headers['content-type'].startswith('text/csv')
