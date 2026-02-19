# Single Restaurant Catering MVP 0.3

Single-restaurant lunch ordering with magic-code login, profile enforcement, today-order confirmation, and minimal restaurant admin.

## Run
```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Environment variables
- `SESSION_SECRET` - strong secret for session middleware cookie signing.
- `ADMIN_USER` / `ADMIN_PASS` - HTTP Basic credentials for `/admin/*` and `/api/v1/admin/*`.
- `APP_ENV=dev` - in dev, if admin env vars are missing, fallback `admin/admin` is enabled with warning log.
- `DEBUG_UI=1` - show debug build badge in order UI.

## Login flow (magic code)
1. Open `http://127.0.0.1:8000/login`.
2. Enter email and click **Send code**.
3. In dev mode read code from server logs:
   - `[LOGIN] Magic code for <email>: <code>`
4. Enter code and click **Login**.
5. Session persists on refresh until `/logout`.

Limits:
- max 5 send-code requests / 10 minutes per email
- max 10 verify attempts / 10 minutes per email
- code expires in 10 minutes

## Main URLs
- `/` - customer order page
- `/login` - magic-code login
- `/logout` - session clear + redirect login
- `/profile` - customer profile (name, postal code, company)
- `/my-order` - latest today order details
- `/admin/orders/today` - admin today orders table

`/docs` remains available for OpenAPI docs.

## Customer ordering notes
- Company is required before placing an order.
- Order page blocks cart actions and checkout until company is selected.
- Successful order shows confirmation block with totals, delivery window, payment, and items.
- Local cart is cleared only after successful order response.
- `GET /api/v1/orders/me/today` returns latest today order or `null`.

## Admin notes
- Admin uses HTTP Basic Auth (`ADMIN_USER` / `ADMIN_PASS`).
- Today orders page supports status actions and CSV export.
- CSV download path: `/admin/orders/today.csv` (API: `/api/v1/admin/orders/today.csv`).
