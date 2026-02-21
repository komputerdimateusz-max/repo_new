# Single Restaurant Catering MVP 0.4

Single-restaurant lunch ordering with permanent username/password accounts and role-based panels.

## Run
```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Environment variables
- `SESSION_SECRET` - strong secret for session middleware cookie signing.
- `APP_ENV=dev` - development mode.
- `DEBUG_UI=1` - show debug build badge in order UI.

## Authentication and roles
Roles:
- `ADMIN` - manages users and can access restaurant/admin pages.
- `RESTAURANT` - manages menu and restaurant settings.
- `CUSTOMER` - places orders.

On first startup, if no admin exists, the app creates:
- username: `admin`
- password: `123`

> DEV WARNING: default credentials are insecure. Change password immediately.

## Login flow
1. Open `http://127.0.0.1:8000/login`.
2. Log in with `admin / 123`.
3. Go to `/admin/users/new` and create a `RESTAURANT` user.
4. Restaurant user logs in and uses `/restaurant/menu` to create/edit menu items.
5. Create `CUSTOMER` users from admin panel to access `/` ordering page.

## Mandatory admin smoke test (user management)
1. Login as `admin / 123`.
2. Go to `/admin/users/new`.
3. Create user:
   - username: `restauracja`
   - password: `test123`
   - role: `RESTAURANT`
4. Logout and login as `restauracja / test123`.
5. Confirm you land on `/restaurant`.

## Manual smoke test: admin role update
1. Login as `admin / 123`.
2. Open `/admin/users/<id>` for any existing user.
3. Change role to `RESTAURANT`.
4. Click save.
5. Confirm the page reloads without Internal Server Error and the role is updated.

## Main URLs
- `/` - customer order page
- `/login` - username/password login
- `/admin` - admin home
- `/admin/users` - user management
- `/restaurant` - restaurant panel
- `/restaurant/menu` - menu CRUD
- `/restaurant/settings` - cut-off/delivery settings

`/docs` remains available for OpenAPI docs.


## Manual role-separation test checklist
1. Start app and log in as `admin / 123`.
2. Open `/admin/users` and create:
   - `restaurant1 / pass / RESTAURANT`
   - `customer1 / pass / CUSTOMER`
3. Logout, log in as `restaurant1`, open `/restaurant/menu`, add a new menu item.
4. Logout, log in as `customer1`, open `/` and verify the newly added item is visible.
5. Verify customer role is blocked from `/admin` and `/restaurant`.

## Vertical slice smoke test (restaurant -> customer cart)
1. Login as `RESTAURANT`.
2. Open `/restaurant/menu` and add item: name `Test dish`, price `10.00`.
3. Open `/__debug/menu` and confirm `Test dish` exists.
4. Login as `CUSTOMER`, open `/` and confirm `Test dish` is visible.
5. Click `Dodaj` and confirm item appears in `Twój koszyk` with updated total.
