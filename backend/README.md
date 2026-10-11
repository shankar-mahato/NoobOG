# NoobOG website backend

Django website, PostgreSQL-backed booking domain, and REST API.

## Local development

Requirements: Python 3.10+, pip, and Docker with the Compose plugin for PostgreSQL.

```sh
cd backend
docker compose up -d db
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=True
export DATABASE_URL=postgres://playslot:playslot@127.0.0.1:5432/playslot
python manage.py migrate
python manage.py runserver
```

The player website is at `/`; vendors register and sign in through `/vendor/`. The API is at `/api/v1/`. `.env.example` documents the supported environment variables; export them in your shell for local development or configure them in your deployment provider.

For a database-free test run:

```sh
DATABASE_URL=sqlite:///:memory: python manage.py check
DATABASE_URL=sqlite:///:memory: python manage.py test
```

## API reference

- Interactive Swagger UI: `/api/docs/`
- OpenAPI schema: `/api/schema/`
- Authentication: token header `Authorization: Token <token>`.

### Authentication

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/player/register/` | Register a player and return a token |
| `POST` | `/api/v1/auth/vendor/register/` | Register a vendor and return a token |
| `POST` | `/api/v1/auth/player/login/` | Log in as a player |
| `POST` | `/api/v1/auth/vendor/login/` | Log in as a vendor |
| `POST` | `/api/v1/auth/logout/` | Revoke the authenticated token |

Registration accepts `username`, `email`, and `password`. Login accepts `username` and `password`. Successful authentication returns a `token` and a `user` object with `id`, `username`, `email`, and `role`.

### Public player discovery and bookings

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/venues/?q=&category=` | Search active venues by name, address, city, state, country, PIN/postal code, or description; category is `pc`, `console`, `vr`, `snooker`, `turf`, `swimming`, or `ground` |
| `GET` | `/api/v1/venues/{venue_id}/` | Get an active venue |
| `GET` | `/api/v1/venues/{venue_id}/availability/?date=YYYY-MM-DD` | Get available start times and durations |
| `POST` | `/api/v1/venues/{venue_id}/bookings/` | Request a session as an authenticated player |
| `GET` | `/api/v1/player/bookings/` | List the authenticated player's bookings |

Booking requests accept `game_date`, a `start_time` on a 30-minute boundary (for example `10:30:00`), and `duration_hours` (`1`, `1.5`, or `2`). Start times and durations are generated within each venue's configured opening/closing hours; 12:00 AM as the closing time represents midnight. A new request has `pending` status and reserves capacity until the vendor responds.

### Vendor management

| Method | Endpoint | Purpose |
|---|---|---|
| `GET`, `POST` | `/api/v1/vendor/venues/` | List only the signed-in vendor's venues or create a venue |
| `GET`, `PATCH` | `/api/v1/vendor/venues/{venue_id}/` | Read/update an owned venue |
| `GET` | `/api/v1/vendor/bookings/?status=&date=` | List bookings for the vendor's venues |
| `POST` | `/api/v1/vendor/bookings/{booking_id}/accept/` | Accept a pending request |
| `POST` | `/api/v1/vendor/bookings/{booking_id}/release/` | Release a pending request |

Vendor endpoints enforce account role and venue ownership. Venue create/update accepts `name`, `location`, `address_line`, `city`, `state`, `country`, `postal_code`, `category`, `photo`, `description`, `hourly_rate`, `system_count`, `opening_time`, `closing_time`, and `is_active`; `photo` is an optional image upload up to 5 MB and must be sent as multipart form data. Address fields and `postal_code` support local discovery, `system_count` controls overlap capacity, and opening/closing hours drive automatically generated availability. `location` remains as a legacy compatibility field.

### Example

```sh
curl -X POST http://127.0.0.1:8000/api/v1/auth/player/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"player","password":"your-password"}'

curl http://127.0.0.1:8000/api/v1/venues/ \
  -H 'Accept: application/json'
```

## Deploy

Deploy this folder as the Django service root. Install `requirements.txt`, then run:

```sh
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn playslot.wsgi:application --bind 0.0.0.0:$PORT
```

Configure `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL` (PostgreSQL), and, when required, `CSRF_TRUSTED_ORIGINS`. Email notifications use `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, and `DEFAULT_FROM_EMAIL`. Static files are served by WhiteNoise. Venue photos are user-uploaded media: configure `DJANGO_MEDIA_ROOT` to a persistent volume and serve `/media/` through that volume, a reverse proxy, or an object-storage backend. Django's development media handler is enabled only when `DEBUG=True` and is not suitable for production. The Django templates and static assets are in the sibling `frontend/web/` directory and should be included in the deployment checkout.

Booking writes lock the venue row and check system capacity across the full requested interval inside a transaction to prevent concurrent overbooking.
