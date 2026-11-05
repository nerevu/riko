---
source: ../../../../nerevu-api/README.md
---

# Nerevu API

Nerevu's monolith ("God") API — a [Flask](https://flask.palletsprojects.com/) service
that provides a single OAuth2-authenticated REST API over many third-party providers and
syncs data between them. Its core job is pulling time entries from **Timely**,
**Airtable**, and **Google Sheets** into **Xero Projects** for billing and invoicing,
with supporting integrations for email, storage, and webhooks. Timely and Airtable
time is synced in batches with `manage sync`; Google Sheets rows reach Xero through the
`gsheets-hooks` `new_row` webhook, which runs the same `add_xero_time` action.

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

- **`app/routes/`** — Flask routes. `api` and `housekeeping` are the two blueprints
  `create_app` registers. `api` mounts the OAuth `auth` views, the `webhook` views, the
  mailing-list `subscription` view, and `memoization` as method views.
  `housekeeping` redirects trailing-slash URLs and turns every exception into a JSON
  error response. `rq` (job dashboard and job-result routes) is intended:
  `app/routes/rq.py` defines `Expensive` and `Result` views on a blueprint that
  nothing imports or registers, and no `rq-dashboard` package is installed, so no RQ
  routes are served.
- **`app/providers/`** — one module per third-party integration.
- **`app/mappings/`, `app/data/`** — resource mappings (`app/mappings/*.json`: contacts,
  events, items, labels, projects, project users, tasks, time, users) and cached
  provider data (`app/data/<provider>_<collection>.json`, plus `sync_results.json`).
- **`app/authclient.py`** — OAuth2 client handling for the authenticated providers.
- **`app/headless.py`** — Selenium/headless-Chrome automation for providers without an
  API.
- **`worker.py`** — [RQ](https://python-rq.org/) worker for background jobs
  (Redis-backed).

## API

All resources are served under the `/v1` prefix and are provider-scoped
(e.g. `/v1/timely-time`, `/v1/xero-projects`). A `/v1/<provider>-<resource>` route
exists only when the provider is one of the authenticated providers (`airtable`,
`gsheets`, `mailgun`, `postmark`, `timely`, `xero`) and its module defines that
resource; the Providers column lists which. Highlights:

| Route | Methods | Providers | Description |
| ----- | ------- | --------- | ----------- |
| `/`, `/v1` | GET | | API documentation / link index |
| `/v1/ipsum` | GET | | Random sentence (health check) |
| `/v1/<provider>-auth` | GET, PATCH | all six | Begin / manage OAuth for a provider |
| `/v1/<provider>-callback` | GET | all six | OAuth redirect callback |
| `/v1/<provider>-status` | GET | gsheets, timely, xero | Provider auth/connection status |
| `/v1/<provider>-projects` | GET, POST | airtable, gsheets, timely, xero | Projects |
| `/v1/<provider>-time` | GET, PATCH | airtable, gsheets, timely | Time entries |
| `/v1/<provider>-projecttasks` | GET, POST | airtable, gsheets, timely, xero | A project's tasks |
| `/v1/<provider>-projecttime` | GET, POST | airtable, gsheets, timely, xero | A project's time entries (`POST /v1/xero-projecttime` adds a source event to Xero) |
| `/v1/<provider>-tasks` | GET | airtable, gsheets, timely | Provider resources |
| `/v1/<provider>-users` | GET | airtable, gsheets, timely, xero | Provider resources |
| `/v1/<provider>-contacts` | GET | gsheets, timely, xero | Provider resources |
| `/v1/<provider>-inventory` | GET | xero | Provider resources |
| `/v1/<provider>-invoices` | GET, POST | xero | Invoices |
| `/v1/<provider>-onlineinvoices` | GET | xero | Online invoice links |
| `/v1/<provider>-invoicenotification` | GET | | Invoice notification (intended; no provider defines it, so no route is registered) |
| `/v1/<provider>-email` | POST | mailgun, postmark | Send email |
| `/v1/subscription` | GET, POST | | Mailing-list subscription |
| `/v1/<provider>-hooks[/<activity>]` | GET, POST | xero, heroku, timely, gsheets, nerevu | Inbound webhooks |
| `/v1/memoization/<path>` | GET, DELETE | | Inspect / clear the memoization cache (fails today, see [Known issues](#known-issues)) |

Webhook activities (`WEBHOOKS` in `config.py`):

| Route | Activity | Action |
| ----- | -------- | ------ |
| `/v1/heroku-hooks` | `update` | Invalidate the CloudFront distribution |
| `/v1/timely-hooks` | `new_event` | Add the event to Xero (`add_xero_time`) |
| `/v1/gsheets-hooks` | `new_row` | Add the row to Xero (`add_xero_time`) |
| `/v1/nerevu-hooks` | `new_invoice`, `new_charge`, `new_payment` | Email an invoice or payment notification through Postmark from `billing@nerevu.com` (templates 12058975, 16342429, 9956182) |
| `/v1/xero-hooks` | none | Verifies the `x-xero-signature` HMAC; no actions |

Signature checks (intended; no `POST` is verified today, see
[Known issues](#known-issues)):

- `xero`: HMAC-SHA256 of the body with `XERO_WEBHOOK_SECRET`, base64, compared with the
  `x-xero-signature` header.
- `heroku`: `HEROKU_WEBHOOK_SECRET` and the `Heroku-Webhook-Hmac-SHA256` header are
  configured, but the signature is ignored.
- `nerevu`: the signature is ignored.
- `timely`, `gsheets`: no secret or payload key is configured, so a verified check
  would reject every `POST` with `401 Missing payload key!`.

`GET` on a hooks route lists its activities; `GET .../<activity>` describes the action
and its configured keyword arguments.

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

On a production server, `create_app` logs an error for each missing required setting
(it still starts): `API_SECRET`, `MAILGUN_DOMAIN`, `MAILGUN_SMTP_PASSWORD`,
`MAILGUN_API_KEY`, `POSTMARK_SERVER_TOKEN`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `CLOUDFRONT_DISTRIBUTION_ID`,
`XERO_WEBHOOK_SECRET`, `HEROKU_WEBHOOK_SECRET`, `RQ_DASHBOARD_USERNAME`, and
`RQ_DASHBOARD_PASSWORD` (the RQ dashboard credentials are required even though the
dashboard is not served). Optional settings, logged when missing: `VERBOSITY`,
`XERO_USERNAME` / `XERO_PASSWORD` (headless Xero login), `MAILGUN_LIST_PREFIX`,
`MAILGUN_PUBLIC_KEY`, `POSTMARK_ACCOUNT_TOKEN`, and `POSTMARK_TEMPLATE_ID`. Other
variables read by `config.py`: `AIRTABLE_TABLE`, `TIMELY_ACCOUNT_ID`,
`TIMELY_USERNAME` / `TIMELY_PASSWORD`, `GOOGLE_USERNAME` / `GOOGLE_PASSWORD`, and
`DATABASE_URL` (production database).

`manage` loads a config mode with `-m/--config-mode`: `Development` (the default; debug,
SQLite `app.db`), `Test`, `Production`, `Heroku`, `Custom`, or `Ngrok`.
`-f/--config-file` (a Python config file) overrides `-E/--config-envvar` (an env var
naming one), which overrides `-m`. Fixed settings in `config.py` include `REPORT_DAYS`
(90, the default sync/store window) and `ROUTE_TIMEOUT` (0, the `max_age` the `/`,
`/v1`, and `/v1/ipsum` routes pass to `cache_header`, so they send no-cache headers).

> **Security:** `.env` (git-ignored) and the committed `internal-256716-*.json` (a
> Google service-account key) contain live credentials. Rotate them and keep secrets
> out of version control.

You'll need your own
[Xero](https://developer.xero.com/documentation/getting-started/getting-started-guide)
and [Timely](https://dev.timelyapp.com/) developer apps for OAuth.

### 3. Headless Chrome (optional)

Some providers use Selenium. Install a chromedriver:

```bash
brew install chromedriver     # or: sudo port install chromedriver
```

## Running

Development server:

```bash
manage run
```

`manage run` is Flask's dev server; `manage serve` only prints
"Deprecated. Use `manage run` instead."

Production (from the `Procfile`, gunicorn + gevent):

```bash
gunicorn "app:create_app(config_mode='Custom')" -w 3 -k gevent
```

Background worker:

```bash
manage work            # or: python worker.py
```

`manage work -l high -l default` listens on the given priority queues (default: `high`,
`default`, and `low`). It needs Redis; without a Redis connection it logs
"Redis connection not found!" and exits.

## CLI (`manage`)

The `manage` command (`manage.py`) drives the sync pipeline and dev tasks. Run
`manage <command> --help` for options. Global options come before the command:
`-m/--config-mode`, `-f/--config-file`, `-E/--config-envvar` (see
[Configure](#2-configure)), `-v` (repeat for more logging), and `-q` (errors only).

| Command | Description |
| ------- | ----------- |
| `run` | Run the Flask dev server (`serve` is deprecated and only points here); Flask also adds `shell` and `routes` |
| `sync` | Sync a source provider's data into Xero (`-P/--source-prefix`, `-p/--project-id`; see [Sync](#sync)) |
| `store` | Fetch and cache a provider's collection (`-P/--prefix` `timely`\|`xero`\|`airtable`, default `xero`; `-c` collection, default `users`; `-i` resource id; `-s`/`-E` start/end dates, default the last 90 days; `--headless`, …) |
| `prune` | Prune stale cached mappings (`-P/--source-prefix` `timely`\|`airtable`; `-c` collection, default `users`): keeps the newest mapping per Xero id whose source ids still exist |
| `notify` | Send a Xero invoice notification email through Postmark: `manage notify <resource-id> -a invoice\|charge\|payment` (default `invoice`), with `-e`/`-n` sender (default `billing@nerevu.com`, "Nerevu Billing Team"), `-r`/`-m` recipient, `-c` cc, `-t` Postmark template id (no default), `-d/--dry-run`, and `-p/--prompt` (ask before sending) |
| `work` | Run the RQ worker (`-l/--listen` queues) |
| `test-oauth` | Exercise an authenticated Xero request (`-m` method, default `get`; `-r` resource `time`\|`task`\|`project`\|`contact`, default `time`; `-p` Xero project id) |
| `check` / `lint` / `prettify` | Lint staged changes / ruff / format |
| `deploy` / `add-keys` | Heroku deploy helpers: `deploy -r <remote>` runs `git push origin master` for `-r production`, else `git push origin features`; `add-keys -r <remote>` adds `~/.ssh/id_rsa.pub` with `heroku keys:add` (default remote `staging`) |
| `help` | List the commands |

### Sync

`manage sync -P timely -p <project-id>` copies one source project's time into Xero in
two phases:

1. **Add.** For each event position from `-S/--start-pos` (default 0) up to
   `-n/--end-pos` (or until the source runs out of events), it adds the event to the
   matching Xero project as a time entry (`add_xero_time`). An event already recorded
   as added in `sync_results.json`, or already billed, returns a conflict and counts as
   added, so re-running a sync is safe. An event that fails for another reason (no
   label, day, or duration) is skipped. A `401` while adding aborts the sync with
   exit code 1.
2. **Mark billed.** Each added event is then patched in the source (`mark_billed`) so
   it isn't billed twice. Events whose patch fails are counted as unpatched.

Options: `-P/--source-prefix` (`timely` or `airtable`, default `timely`),
`-p/--project-id` (default `2389295`, a Timely project), `-S/--start-pos`,
`-n/--end-pos`, `-s/--start` and `-E/--end` (the date window, `YYYY-MM-DD` or
`MM/DD/YY`; default the last 90 days, `REPORT_DAYS`), `-d/--dry-run`, `-D/--debug`,
and `-v`.

After each event the results are saved to `app/data/sync_results.json` as
`{"<event id>": {"added": bool, "patched": bool}}`, unless `--dry-run` is given. They
are also saved on Ctrl-C, on Ctrl-Z, and when an exception escapes. The exit code is
the number of skipped plus unpatched events, so `0` means every event was added and
marked billed.

### Sync scripts

`bin/` wraps the CLI for common batch jobs:

```bash
bin/sync-time     # sync Timely + Airtable time into Xero, then sync-data
bin/sync-data     # store users, projects, events, tasks, xero inventory; prune mappings
```

`bin/sync-time` runs `manage sync` for every project id in
`app/data/timely_projects.json` and then `app/data/airtable_projects.json`, passing its
arguments through, and stops at the first project whose sync exits non-zero.

Individual `store-*` scripts (`store-users`, `store-projects`, `store-events`,
`store-tasks`, `store-xero-inventory`, `prune-mappings`) are also available.

## Development

```bash
manage lint       # ruff check (-f to fix, -s to add pylint, -w <paths>)
manage prettify   # ruff format (-s also sorts imports)
manage test       # (intended; Heroku CI: manage -m Heroku test)
```

There is no `test` command or test suite today: `manage test` fails with
"No such command 'test'". `tox.ini` still runs `manage test` and `manage lint`.

## Known issues

- Webhook `POST`s are never signature-checked: `Webhook.post` tests `if self.verified:`
  (`app/routes/webhook.py:116`) without calling the method, so every `POST` is
  accepted and its activity runs.
- `/v1/<provider>-invoicenotification` is listed in `method_views` (`api.py:114-117`),
  but no provider defines an `InvoiceNotification` resource, so the route is never
  registered.
- `/v1/memoization/<path>` always fails with a 500 `TypeError` JSON error:
  `api.py:130` instantiates the view with a prefix argument, but `Memoization.__init__`
  (`app/routes/__init__.py:83-84`) accepts none. The route is only registered with a
  `<path>`, so the clear-everything branch has no URL.
- `manage notify -a payment` sends an invoice notification: `ACTIONS["payment"]` is
  `send_invoice_notification` (`manage.py:51`), not `send_payment_notification`.
- `manage prune` computes the pruned mappings but never saves them: it only rebinds a
  local variable (`manage.py:271`).
- `manage work` raises `TypeError` when Redis is connected: `worker.py:27` `sum`s
  lists of failed job ids.
- `manage lint -s` runs pylint with `--rcfile=tests/standard.rc` (`manage.py:627`), but
  there is no `tests/` directory.
- `bin/sync-time` exits `0` after "Sync exited with failures": its bare `exit` returns
  the status of the preceding `echo`.
- `manage test-oauth -r invoice` raises `KeyError`: `invoice` has a URL but no sample
  data (`DATA`, `manage.py:358`; `URLS`, `manage.py:385-391`).
