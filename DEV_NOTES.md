# DEV Notes: Weekly Menu MVP

## Quick smoke run
1. Start app and sign in as admin.
2. In **Dashboard → Weekly menu**, choose a future date (within 7 days).
3. In **Catering menu**, create catalog dishes and mark selected ones as **Standard dish**.
4. Back in **Weekly menu**, click **Enable standard dishes for this date**.
5. Sign in as employee and open **Place an Order**.
6. Select the same date and confirm menu items are visible and can be ordered.
7. Open **Orders** (catering/admin) and pick the same date to verify totals by location.

## Notes
- Weekly ordering horizon is enforced on backend (`today..today+6`).
- SQLite migration is handled via `ensure_sqlite_schema(engine)` (no Alembic).
