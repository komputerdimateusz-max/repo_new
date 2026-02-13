# DEV Notes: Weekly Menu MVP

## Quick smoke run
1. Start app and sign in as admin.
2. In **Dashboard → Weekly menu**, choose a future date (within 7 days).
3. In **Catering menu**, create catalog dishes and mark selected ones as **Standard dish**.
4. Back in **Weekly menu**, click **Enable standard dishes for this date**.
5. Sign in as customer and open **Place an Order**.
6. Select the same date and confirm menu items are visible and can be ordered.
7. Open **Orders** (restaurant/admin) and pick the same date to verify totals by location.

## Notes
- Weekly ordering horizon is enforced on backend (`today..today+6`).
- SQLite migration is handled via `ensure_sqlite_schema(engine)` (no Alembic).

## Marketplace MVP (multi-restaurant)

- Added `restaurants`, `restaurant_opening_hours`, and `restaurant_locations` tables.
- Added `restaurant_id` to `catalog_items`, `daily_menu_items`, `orders`, and `users` (nullable for users).
- SQLite lightweight migration (`ensure_sqlite_schema`) now:
  - creates new restaurant tables,
  - adds new columns when missing,
  - creates default `Default Restaurant`,
  - backfills all legacy rows to that default restaurant,
  - seeds delivery mapping from default restaurant to active locations when no mapping exists.
- Ordering flow now requires both location and restaurant; menu is shown per selected restaurant.
- Cutoff logic resolves as: `RestaurantLocation.cut_off_time_override` -> `Location.cutoff_time` -> app default.
- Catering role is scoped to one restaurant via `users.restaurant_id`.


Role model: admin, customer, restaurant. Restaurant users must have restaurant_id; customers must not.

## Order status flow manual check

1. Create restaurant user and place a customer order.
2. Open **Catering → Orders** as restaurant and verify status starts as `pending`.
3. Click **Confirm** and verify the order becomes `confirmed`.
4. Click **Mark prepared** and verify the order becomes `prepared`.
5. Click **Mark delivered** and verify the order becomes `delivered`.
6. Try invalid transition (for example posting `delivered -> prepared`) and verify it is blocked with an error message.
7. Ensure a restaurant user cannot modify orders from another restaurant (returns 403).
