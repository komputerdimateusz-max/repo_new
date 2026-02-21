from decimal import Decimal
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


def test_order_requires_company_selection_message() -> None:
    allow_orders_now()
    login_customer()

    client.patch('/api/v1/me', json={'name': 'Pilot User', 'postal_code': '66-400', 'company_id': None})
    menu = client.get('/api/v1/menu/today').json()
    first_item_id = menu['items'][0]['id']
    order = client.post('/api/v1/orders', json={'payment_method': 'BLIK', 'items': [{'menu_item_id': first_item_id, 'qty': 1}]})

    assert order.status_code == 400
    assert order.json()['detail'] == 'Select company in profile first.'


def test_cutlery_addon_settings_and_order_totals() -> None:
    login_admin()
    save_settings = client.post(
        '/restaurant/settings',
        data={
            'cut_off_time': '23:59',
            'delivery_fee': '5.00',
            'cutlery_price': '1.50',
            'delivery_window_start': '12:00',
            'delivery_window_end': '13:00',
        },
        follow_redirects=False,
    )
    assert save_settings.status_code == 303

    login_customer()
    companies = client.get('/api/v1/companies').json()
    company_id = companies[0]['id']
    updated = client.patch('/api/v1/me', json={'name': 'Pilot User', 'postal_code': '66-400', 'company_id': company_id})
    assert updated.status_code == 200

    settings_payload = client.get('/api/v1/settings').json()
    assert settings_payload['cutlery_price'] == '1.50'

    menu = client.get('/api/v1/menu/today').json()
    first_item = menu['items'][0]
    first_item_id = first_item['id']
    item_price = Decimal(first_item['price'])

    with_cutlery = client.post(
        '/api/v1/orders',
        json={
            'payment_method': 'BLIK',
            'cutlery': True,
            'cutlery_price': 999,
            'items': [{'menu_item_id': first_item_id, 'qty': 1}],
        },
    )
    assert with_cutlery.status_code == 200
    with_cutlery_payload = with_cutlery.json()
    assert with_cutlery_payload['cutlery'] is True
    assert Decimal(with_cutlery_payload['cutlery_price']) == Decimal('1.50')
    assert Decimal(with_cutlery_payload['subtotal_amount']) == item_price
    assert Decimal(with_cutlery_payload['extras_total']) == Decimal('1.50')

    without_cutlery = client.post(
        '/api/v1/orders',
        json={
            'payment_method': 'BLIK',
            'cutlery': False,
            'cutlery_price': 1.5,
            'items': [{'menu_item_id': first_item_id, 'qty': 1}],
        },
    )
    assert without_cutlery.status_code == 200
    without_cutlery_payload = without_cutlery.json()
    assert without_cutlery_payload['cutlery'] is False
    assert Decimal(without_cutlery_payload['extras_total']) == Decimal('0.00')

    total_diff = Decimal(with_cutlery_payload['total_amount']) - Decimal(without_cutlery_payload['total_amount'])
    assert total_diff == Decimal('1.50')
