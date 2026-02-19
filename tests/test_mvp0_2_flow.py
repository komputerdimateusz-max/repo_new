import base64

from fastapi.testclient import TestClient

from app.main import MAGIC_CODES, app, startup
from app.db.session import SessionLocal
from app.models import RestaurantSetting

startup()
client = TestClient(app)


def allow_orders_now() -> None:
    with SessionLocal() as db:
        settings = db.get(RestaurantSetting, 1)
        settings.cut_off_time = "23:59"
        db.commit()


def login(email: str = "pilot@example.com") -> None:
    client.post('/login/send', json={'email': email})
    code = MAGIC_CODES[email]["code"]
    response = client.post('/login/verify', json={'email': email, 'code': code}, follow_redirects=False)
    assert response.status_code == 303


def admin_headers() -> dict[str, str]:
    token = base64.b64encode(b"admin:admin").decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def test_root_requires_login() -> None:
    anonymous = TestClient(app)
    response = anonymous.get('/', follow_redirects=False)
    assert response.status_code == 307
    assert response.headers['location'] == '/login'


def test_me_update_and_order_flow() -> None:
    allow_orders_now()
    login()
    me = client.get('/api/v1/me')
    assert me.status_code == 200

    companies = client.get('/api/v1/companies').json()
    company_id = companies[0]['id']
    updated = client.patch('/api/v1/me', json={'name': 'Pilot User', 'postal_code': '66-400', 'company_id': company_id})
    assert updated.status_code == 200
    assert updated.json()['name'] == 'Pilot User'

    menu = client.get('/api/v1/menu/today').json()
    first_item_id = menu['items'][0]['id']
    order = client.post('/api/v1/orders', json={'payment_method': 'BLIK', 'items': [{'menu_item_id': first_item_id, 'qty': 1}]})
    assert order.status_code == 200

    my_order = client.get('/api/v1/orders/me/today')
    assert my_order.status_code == 200
    assert my_order.json()['order_id'] >= 1


def test_admin_settings_requires_basic_auth_and_csv_export() -> None:
    noauth = client.get('/api/v1/admin/settings')
    assert noauth.status_code == 401

    settings_response = client.get('/api/v1/admin/settings', headers=admin_headers())
    assert settings_response.status_code == 200

    export = client.get('/api/v1/admin/orders/today.csv', headers=admin_headers())
    assert export.status_code == 200
    assert export.headers['content-type'].startswith('text/csv')
