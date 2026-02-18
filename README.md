# Single Restaurant Catering MVP 1.0

This project is now a strict MVP for one-restaurant catering.

## Scope
- Exactly one restaurant in the system.
- Customers do not pick a restaurant.
- Orders are for today only.
- One global cut-off time controls ordering.

## Backend
- FastAPI endpoints under:
  - `/api/v1/admin`
  - `/api/v1/order`
- SQLAlchemy models for:
  - Restaurant (global cut-off)
  - Location
  - Company
  - Customer
  - MenuItem
  - DailySpecial
  - Order / OrderItem

## Web URLs
- UI: `http://127.0.0.1:8000/`
- API root: `http://127.0.0.1:8000/api`
- API docs: `http://127.0.0.1:8000/docs`

## Streamlit UIs
- Admin panel: `streamlit run streamlit_app/admin.py`
- Customer ordering page: `streamlit run streamlit_app/order.py`

## Run API
```bash
uvicorn app.main:app --reload
```
