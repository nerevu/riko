# Nerevu API

Nerevu's monolith ("God") API — a [Flask](https://flask.palletsprojects.com/) service
that provides a single OAuth2-authenticated REST API over many third-party providers and
syncs data between them. Its core job is pulling time entries from **Timely**,
**Airtable**, and **Google Sheets** into **Xero Projects** for billing and invoicing,
with supporting integrations for email, storage, and webhooks.

- **Version:** 0.34.0
- **License:** MIT
- **Python:** ≥ 3.10 (targets 3.12)

## Providers

The API brokers requests to, and syncs data across, these providers
(`app/providers/`):

| Provider | Used for |
| -------- | -------- |
| Timely | Time tracking source |
| Xero | Accounting — projects, time, invoices, inventory |
| Airtable | Time/data source |
| Google Sheets | Time/data source |
| Mailgun | Email + mailing lists |
| Postmark | Transactional email |
| AWS | S3 / CloudFront storage + invalidation |
| Heroku | Deploy webhooks |
| Nerevu | Internal resources |

## Architecture

- **`app/routes/`** — Flask blueprints: the REST `api`, OAuth `auth`, `webhook`,
  `subscription`, `rq` (job dashboard), and `housekeeping`.
- **`app/providers/`** — one module per third-party integration.
- **`app/mappings/`, `app/data/`** — resource mappings and cached provider data.
- **`app/authclient.py`** — OAuth2 client handling for the authenticated providers.
- **`app/headless.py`** — Selenium/headless-Chrome automation for providers without an API.
- **`worker.py`** — [RQ](https://python-rq.org/) worker for background jobs (Redis-backed).

## API

All resources are served under the `/v1` prefix and are provider-scoped
(e.g. `/v1/timely-time`, `/v1/xero-projects`). Highlights:

| Route | Methods | Description |
| ----- | ------- | ----------- |
| `/`, `/v1` | GET | API documentation / link index |
| `/v1/ipsum` | GET | Random sentence (health check) |
| `/v1/<provider>-auth` | GET, PATCH | Begin / manage OAuth for a provider |
| `/v1/<provider>-callback` | GET | OAuth redirect callback |
| `/v1/<provider>-status` | GET | Provider auth/connection status |
| `/v1/<provider>-projects` | GET, POST | Projects |
| `/v1/<provider>-time` | GET, PATCH | Time entries |
| `/v1/<provider>-tasks`, `-users`, `-contacts`, `-inventory` | GET | Provider resources |
| `/v1/<provider>-invoices` | GET, POST | Invoices |
| `/v1/<provider>-email` | POST | Send email |
| `/v1/subscription` | GET, POST | Mailing-list subscription |
| `/v1/<provider>-hooks[/<activity>]` | GET, POST | Inbound webhooks |
| `/v1/memoization/<path>` | GET, DELETE | Inspect / clear the memoization cache |

## Setup

### 1. Install

```bash
python -m venv env && source env/bin/activate   # Windows: ./env/Scripts/activate
pip install -r requirements.txt
pip install -r dev-requirements.txt              # contributors
```

### 2. Configure

Copy `.env.example` to `.env` and fill in the values (loaded via `python-dotenv`):

```bash
cp .env.example .env
```

Key variables include `API_SECRET` (Flask secret), the OAuth credentials for each
provider (`TIMELY_CLIENT_ID` / `TIMELY_SECRET`, `XERO_CLIENT_ID` / `XERO_SECRET`),
`AIRTABLE_PAT` / `AIRTABLE_BASE_ID`, the `MAILGUN_*`, `POSTMARK_*`, and `AWS_*` keys,
the `*_WEBHOOK_SECRET`s, and the `RQ_DASHBOARD_*` credentials.

> **Security:** the committed `.env` and `internal-256716-*.json` (a Google
> service-account key) contain live credentials. Rotate them and keep secrets out of
> version control.

You'll need your own [Xero](https://developer.xero.com/documentation/getting-started/getting-started-guide)
and [Timely](https://dev.timelyapp.com/) developer apps for OAuth.

### 3. Headless Chrome (optional)

Some providers use Selenium. Install a chromedriver:

```bash
brew install chromedriver     # or: sudo port install chromedriver
```

## Running

Development server:

```bash
manage serve
```

Production (from the `Procfile`, gunicorn + gevent):

```bash
gunicorn "app:create_app(config_mode='Custom')" -w 3 -k gevent
```

Background worker:

```bash
manage work            # or: python worker.py
```

## CLI (`manage`)

The `manage` command (`manage.py`) drives the sync pipeline and dev tasks. Run
`manage <command> --help` for options.

| Command | Description |
| ------- | ----------- |
| `serve` | Run the Flask dev server |
| `sync` | Sync a source provider's data into Xero (`-P/--prefix`, `-p/--project`) |
| `store` | Fetch and cache a provider's collection (`-p`, `-c`, `--headless`, …) |
| `prune` | Prune stale cached mappings |
| `notify` | Trigger a webhook activity/notification |
| `work` | Run the RQ worker |
| `test-oauth` | Exercise an authenticated provider request |
| `check` / `lint` / `prettify` | Lint staged changes / ruff / format |
| `deploy` / `add-keys` | Heroku deploy helpers |

### Sync scripts

`bin/` wraps the CLI for common batch jobs:

```bash
bin/sync-time     # sync Timely + Airtable time into Xero, then sync-data
bin/sync-data     # store users, projects, events, tasks, xero inventory; prune mappings
```

Individual `store-*` scripts (`store-users`, `store-projects`, `store-events`,
`store-tasks`, `store-xero-inventory`, `prune-mappings`) are also available.

## Development

```bash
manage lint       # ruff / flake8
manage prettify   # format
manage test       # (Heroku CI: manage -m Heroku test)
```
