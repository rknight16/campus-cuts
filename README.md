# Campus Cuts Rent Tracking System

COMP2140 Group 3 project. Django + PostgreSQL web app that tracks weekly rent for Campus Cuts Barbershop and Salon (see the SRS and SDS).

## Setup (once)

You need Python 3.10+ and PostgreSQL.

**Mac:** install [Postgres.app](https://postgresapp.com) and open it. **Windows:** install PostgreSQL from postgresql.org and remember the password you set for the `postgres` user.

```bash
git clone <repo link>
cd campus-cuts
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Open `.env` and set `DB_USER` / `DB_PASSWORD` for your PostgreSQL (Postgres.app: user is your Mac username, password blank).

Create the database, set up the tables and load the demo data:

```bash
createdb campuscuts                # or create it in pgAdmin
python manage.py migrate
python manage.py seed
python manage.py runserver
```

Open http://127.0.0.1:8000. The admin site is at http://127.0.0.1:8000/admin/ (log in as `owner`).

## Demo logins

Password for every account: `campuscuts2026`

| Username | Role |
|---|---|
| owner | Owner (Terron Dewar) |
| company | Company Supervisor |
| sup1 ... sup5 | Shop Supervisor of Taylor Hall, Towers Salon, Students' Union, UTech Barbershop, UTech Salon |
| c1002 | Independent contractor at Taylor Hall |
| c1011 | Contractor on commission at the Students' Union |

Contractor usernames are `c` + staff ID (1001 to 1017). `python manage.py seed` wipes and reloads everything, so run it whenever you want a clean demo. It also loads last week's payments, with three contractors short, so the dashboard and overdue screens have something to show.

## Who builds what

| Feature | Owner | Rules (service) | Page (view) |
|---|---|---|---|
| US-01 Record payments | Raynardo | `rent/services/payments.py`, `rent_rules.py` | `rent/views/payments.py` |
| US-02 Weekly rent settings | Jordon Mingoes | `rent/services/rent_settings.py` | `rent/views/rent_settings.py` |
| US-03 Handoffs | Chiantina | `rent/services/handoffs.py` | `rent/views/handoffs.py` |
| US-04 Dashboard | Dylandre | `rent/services/dashboard.py` | `rent/views/dashboard.py` |
| US-05 Contractors | Jordon Stewart | `rent/services/contractors.py` | `rent/views/contractors.py` |
| US-06 My rent | Raynardo | `rent/services/rent_rules.py` | `rent/views/account.py` |
| US-07 Receipts | Jordon Mingoes | `rent/services/receipts.py` | `rent/views/receipts.py` |

Each page already exists as a placeholder with its permission check in place, and each service file lists the functions to write. **Build `rent_rules.py` first.** The dashboard, account page and receipts all need "amount owed / paid / balance".

## Rules everyone follows (this is what the SDS says, and what we'll show in the demo)

1. **Business rules go in `rent/services/`**, not in views or templates. Views read the form, call the service, show the result.
2. **Every view gets a permission check** from `rent/access.py`: `@role_required(...)`, plus `ensure_same_shop(...)` or `ensure_own_contractor(...)` when the page is about one shop or one person. Hiding a link is not enough. People can type the URL.
3. **Never delete payments or handoffs** (SF-1). The models block it. Corrections go in `PaymentCorrection`.
4. **Money is `Decimal`, never `float`.**
5. **Write tests for your feature** in `rent/tests/test_<feature>.py`. Use `make_world()` from `rent/tests/helpers.py`. It sets up the SRS scenario data (Taylor Hall $15,000 due Friday, rent period 2 to 8 Nov 2026). Name each test after the scenario it checks, so it lines up with the test plan.
6. If you add or change a model, run `python manage.py makemigrations` and commit the migration file with your change. Tell the group, because everyone else has to run `migrate`.

Run the tests: `python manage.py test rent`

## Git workflow

```bash
git checkout main && git pull                 # start from the latest
git checkout -b us-03-handoffs                # your own branch
# ... work, then:
git add . && git commit -m "US-03: record shop handoff"
git push -u origin us-03-handoffs             # then open a Pull Request on GitHub
```

Commit small and often, with the US number in the message. Our commit history is the evidence of who built what. Don't commit `.env`.

## Project layout

```
config/            settings (PostgreSQL, Jamaica time, 15-min session timeout), URLs
rent/models.py     all data models (SDS 3.1)
rent/access.py     role and shop permission checks (SE-2)
rent/services/     business rules, one file per feature
rent/views/        pages, one file per feature
rent/templates/    HTML (black-and-white Campus Cuts theme)
rent/management/commands/seed.py   demo data
rent/tests/        tests
```

## Notes for the SDS revision table

These differ from SDS v0.1 and need a line in its revision table:
- Added `CommissionEarning` model (earnings entered for commission contractors, US-01 AC-6).
- Added `Role` as a field on `User` instead of separate `Role`/`RolePermission` classes; permission checks live in `rent/access.py`.
- Session timeout uses Django's session settings (`SESSION_COOKIE_AGE`) instead of a custom `SessionTimeoutMiddleware`.
- Contractor transfers "from the next rent period" (US-05 AC-4) still need a way to store shop history. Decide this in US-05.
