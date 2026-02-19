# Single Restaurant Catering MVP 1.0

This project is a single-restaurant ordering MVP.

## Scope
- Exactly one restaurant in the system.
- Customers do not pick a restaurant.
- Orders are for today only.
- One global cut-off time controls ordering.

## API (MVP0)
- `GET /api/v1/settings`
- `GET /api/v1/companies`
- `GET /api/v1/menu/today?category=...`
- `POST /api/v1/orders`
- `GET /api/v1/orders/today`

## Run API
```bash
uvicorn app.main:app --reload
```

## Migrations
```bash
alembic upgrade head
```

## Manual test checklist
1. Open `http://127.0.0.1:8000/`.
2. Select a company from the dropdown.
3. Add 2 items from the menu.
4. Select payment method (BLIK/KARTA/GOTOWKA).
5. Click "Zamawiam i płacę".
6. Verify the created order in `GET /api/v1/orders/today`.
