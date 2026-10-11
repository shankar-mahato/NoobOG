# NoobOG

NoobOG is a Django gaming-parlour booking website with separate player and vendor experiences. Players can search venues, check automatic availability, and request bookings. Vendors can manage their own venues and accept or release booking requests.

## Project layout

- `backend/` — Django project, booking workflows, optional REST API, and deployment configuration.
- `frontend/web/` — website templates and static assets.

## Run locally

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

Open the player website at <http://127.0.0.1:8000> or the vendor portal at <http://127.0.0.1:8000/vendor/>.

## Website behavior

Availability is generated from each venue's opening and closing hours in 30-minute start increments. Vendors set daily operating hours when listing or editing a venue; session options are generated automatically and unavailable times are omitted. Players choose an activity, date, and session length (1, 1.5, or 2 hours), then review the venue, time, resource, and fee before placing a booking request. Pending and confirmed bookings reserve venue systems during overlapping intervals. Vendors receive booking notifications and can accept or release pending requests.

The homepage activity picker is managed in Django admin at `/admin/booking/activitycategory/`. Administrators can create categories, update their display name, resource label, icon, and order, or deactivate them. Deactivated categories disappear from player discovery and new venue listings, while existing vendor listings retain their category. Search accepts a venue name, area, city, state, country, or PIN/postal code. Vendors provide a complete address line, city, state, country, and postal code for each venue, plus a bookable capacity such as tables, systems, courts, or other units. Players can save favorites, like venues, and revisit recently viewed places; bookings remain available from **My bookings**.

## API documentation

The backend also exposes a REST API at `/api/v1/`, with interactive Swagger documentation at <http://127.0.0.1:8000/api/docs/> and an OpenAPI schema at `/api/schema/`. See [backend/README.md](./backend/README.md) for endpoint details.

## Deployment

Deploy `backend/` as the Django service root and use PostgreSQL. Configuration, environment variables, migrations, and static-file deployment are documented in [backend/README.md](./backend/README.md). Include the sibling `frontend/web/` directory in the deployment checkout.
