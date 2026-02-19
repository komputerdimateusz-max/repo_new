# Single Restaurant Catering MVP 0.2

Single-restaurant lunch ordering with session login, customer profile, and minimal admin tools.

## Run
```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Customer login flow (magic code MVP)
1. Open `http://127.0.0.1:8000/login`.
2. Enter email and click **Send code**.
3. Read the code from server logs (`[MVP login] magic code for ...`).
4. Enter code and click **Login**.
5. You are redirected to `/` and authenticated with session cookie.

## Customer profile and ordering
- `/` requires login and shows logged-in email.
- Company is loaded from `/api/v1/me` and persisted immediately when changed.
- `/profile` lets customer edit `name`, `postal_code`, and `company`.
- `POST /api/v1/orders` derives customer/company from session/profile (payload spoofing ignored).
- Orders are only for **today** and cut-off is enforced server-side.
- `GET /api/v1/orders/me/today` returns the current user’s today orders.

## Admin (single password gate)
- Login page: `/admin/login`
- Password source: `ADMIN_PASSWORD` env var (default `Admin123!`).
- Admin pages:
  - `/admin/settings` (cut-off + delivery settings)
  - `/admin/menu` (menu CRUD)
  - `/admin/specials` (daily special CRUD)
  - `/admin/orders/today` (today table + status updates + CSV export)
- Admin API endpoints are under `/api/v1/admin/*` and require admin session.

## API highlights
- `GET /api/v1/settings`
- `GET /api/v1/companies`
- `GET /api/v1/me`
- `PATCH /api/v1/me`
- `GET /api/v1/menu/today?category=...`
- `POST /api/v1/orders`
- `GET /api/v1/orders/me/today`
- `GET/PATCH /api/v1/admin/settings`
- `GET/POST/PATCH/DELETE /api/v1/admin/menu_items`
- `GET/POST/PATCH/DELETE /api/v1/admin/daily_specials`
- `GET /api/v1/admin/orders/today`
- `PATCH /api/v1/admin/orders/{id}`
- `GET /api/v1/admin/orders/today/export`

## Smoke test checklist
1. Login with magic code and confirm `/` opens.
2. Change company on `/` and refresh (value persists).
3. Place order and confirm inline success + order id.
4. Click **View my today order** and confirm list is shown.
5. Open `/profile`, edit fields, save, and confirm persistence.
6. Open `/admin/login`, login with admin password.
7. Change cut-off or delivery fee in `/admin/settings` and save.
8. Add/remove a menu item in `/admin/menu`.
9. Add/remove a daily special in `/admin/specials`.
10. In `/admin/orders/today`, update status and export CSV.
