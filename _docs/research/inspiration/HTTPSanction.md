---
source: ../../../../HTTPSanction/README.md
---

# HTTPSanction

HTTPSanction is a Flask-based HTTP authentication service meant to centralize OAuth and
API authentication for multiple third-party providers. It exposes a versioned REST API
(`/v1/`), stores provider tokens in the Flask cache, and can fall back to a headless
browser login for providers that define one.

> **Status:** this version does not start. Importing the `app` package fails, so neither
> `./manage.py run` nor the Procfile's gunicorn command serves any route. The sections
> below describe what the code is written to do once it starts; see
> [Known issues](#known-issues).

**Loaded providers:** Airtable, Cloze, GitHub, Gusto, KeyCDN, Mailgun, Postmark,
QuickBooks, Timely, Xero. These are the `providerNames` in
`app/api_configs/default.json`. `app/providers/heroku.json` and
`app/providers/stripe.json` exist but are not loaded, so they get no routes.

Each provider is a JSON file in `app/providers/` (validated by
`app/schemas/provider.schema.json`). It lists one or more `auths` (`authType` is
`oauth2`, `basic`, `bearer`, or `custom` in the shipped files), a `statusResourceId`,
and the `resources` to expose. Any string value that starts with `$` is replaced with
the environment variable of that name (see [Configuration](#configuration)).

## Examples

All endpoints are served under the `/v1` prefix. The home route (`GET /` or `GET /v1`)
returns a JSON index of every registered route.

### Authenticate a provider

Visiting the auth URL for a provider starts its OAuth flow. If the cached token is
valid, the route returns the token state and the provider's status resource instead of
redirecting. An optional `callback_url` query parameter is cached for the callback
route.

```bash
# Start the OAuth flow (redirects to the provider's consent screen)
curl http://localhost:5000/v1/xero-auth

# Check Timely auth status
curl http://localhost:5000/v1/timely-auth

# Fetch the provider's status resource directly
curl http://localhost:5000/v1/xero-status
```

The provider redirects back to `/v1/<prefix>-callback`, which stores the token.

### Fetch a resource collection

```bash
# List all Xero projects
curl http://localhost:5000/v1/xero-projects

# List all Timely time entries
curl http://localhost:5000/v1/timely-time

# List Xero invoices
curl http://localhost:5000/v1/xero-invoices
```

Resource routes take no per-request parameters: query-string and body values are not
read on resource routes (see [Known issues](#known-issues)). The date window and field
list come from the provider JSON.

### Fetch a single resource

There is no `/<id>` URL segment and no request parameter for an item id. A resource
fetches a single item only when its provider JSON pins `rid` (and, for sub-resources,
`srid`), usually to an environment variable. For example, `/v1/xero-project-tasks` and
`/v1/xero-project-time` always read the project in `$XERO_PROJECT_ID`, and
`/v1/timely-project-time` reads the project in `$TIMELY_PROJECT_ID`. The **Pinned id**
column of the [route inventory](#routes) lists these.

Intended usage (returns 404 today):

```bash
# Get a specific Xero contact
curl http://localhost:5000/v1/xero-contacts/<ContactID>

# Get a specific Timely user
curl http://localhost:5000/v1/timely-users/<userId>
```

### Create or update a resource

Several resources list `POST`, `PATCH`, or `DELETE` in their provider JSON (for example
`xero-projects`, `timely-project-time`, `timely-time`), so those methods are routed. The
resource view only implements `GET`, so any other method returns a 500 error.

Intended usage (returns 500 today):

```bash
# Create a Xero project
curl -X POST http://localhost:5000/v1/xero-projects \
  -H "Content-Type: application/json" \
  -d '{"name": "New Project", "status": "INPROGRESS"}'

# Log time on a Timely project
curl -X POST http://localhost:5000/v1/timely-project-time \
  -H "Content-Type: application/json" \
  -d '{"day": "2024-01-15", "duration": {"total_minutes": 90}, "note": "Design review"}'
```

### Refresh or revoke a token

`Auth` has `patch` (renew the token, then redirect to the auth route) and `delete`
(revoke the token) handlers. The `auth` entry in `app/api_configs/default.json` sets no
`methods`, so the auth route is registered for `GET` only, and `PATCH` and `DELETE`
return 405.

Intended usage (returns 405 today):

```bash
# Force token refresh
curl -X PATCH http://localhost:5000/v1/xero-auth

# Revoke token
curl -X DELETE http://localhost:5000/v1/xero-auth
```

### Receive webhooks

Webhooks are not wired in this version. The provider JSON files carry `webhook` settings
(signature header, `$..._WEBHOOK_SECRET`), and `app/webhook.py` and
`app/routes/webhook.py` define a `Webhook` class and view, but no webhook route is
registered.

Intended usage (the route is not registered today):

```bash
# Xero webhook endpoint (configure this URL in your Xero developer portal)
POST http://localhost:5000/v1/xero
```

## Routes

These routes are created by `./manage.py run` for each loaded provider. `<prefix>` is
the provider's `prefix` (the file name, e.g. `xero`).

| Route | Methods | Description |
| --- | --- | --- |
| `/`, `/v1` | GET | JSON index of all routes |
| `/v1/ipsum` | GET | A random sentence (test route) |
| `/v1/memoization` | GET, DELETE | Meant to clear cached responses; crashes (see Known issues) |
| `/v1/<prefix>-auth` | GET | Start OAuth, or report token and status |
| `/v1/<prefix>-callback` | GET | OAuth redirect target; stores the token |
| `/v1/<prefix>-status` | from the status resource | The resource named by `statusResourceId` |
| `/v1/<prefix>-<resource>` | from the resource's `methods` (default `GET`) | One per non-hidden resource; only `GET` works |

The resource route name is the resource's `resourceId` converted to kebab-case
(`project_time` → `project-time`, `ProjectTime` → `project-time`). Provider routes are
only created by the `run` command; an app built any other way (for example by gunicorn)
has none of them.

Resource routes for the loaded providers (upstream path relative to the auth's
`apiBaseURL`; `{rid}`/`{srid}` are filled from the pinned ids):

| Route | Methods | Upstream path | Pinned id |
| --- | --- | --- | --- |
| `/v1/airtable-records` | GET | `{rid}/records` | `$AIRTABLE_BASE_ID` |
| `/v1/airtable-bases` | GET | `bases` |  |
| `/v1/airtable-status` | GET | `bases` (status resource) |  |
| `/v1/airtable-payloads` | GET | `bases/{rid}/webhooks/{srid}/payloads` | `$AIRTABLE_BASE_ID` |
| `/v1/cloze-stages` | GET | `project_segments` |  |
| `/v1/cloze-profile` | GET | `profile` |  |
| `/v1/cloze-status` | GET | `profile` (status resource) |  |
| `/v1/github-organizations` | GET | `organizations` |  |
| `/v1/github-status` | GET | `organizations` (status resource) |  |
| `/v1/gusto-companies` | GET | `companies/{rid}` | `$GUSTO_COMPANY_ID` |
| `/v1/gusto-employees` | GET | `companies/{rid}/employees` | `$GUSTO_COMPANY_ID` |
| `/v1/gusto-me` | GET | `me` |  |
| `/v1/gusto-status` | GET | `me` (status resource) |  |
| `/v1/gusto-payments` | GET | `companies/{rid}/contractor_payments` | `$GUSTO_COMPANY_ID` |
| `/v1/gusto-payrolls` | GET | `companies/{rid}/payrolls` | `$GUSTO_COMPANY_ID` |
| `/v1/keycdn-zones` | GET, PATCH, POST, DELETE | `zones` |  |
| `/v1/keycdn-status` | GET, PATCH, POST, DELETE | `zones` (status resource) |  |
| `/v1/keycdn-zone-cache` | GET, DELETE, POST | `zones/purge/{rid}` | `$KEYCDN_ZONE_ID` |
| `/v1/keycdn-zone-url-cache` | DELETE | `zones/purgeurl/{rid}` | `$KEYCDN_ZONE_ID` |
| `/v1/mailgun-domains` | GET | `domains` |  |
| `/v1/mailgun-status` | GET | `domains` (status resource) |  |
| `/v1/mailgun-email-lists` | GET | `lists/pages` |  |
| `/v1/mailgun-email-list` | GET | `lists/{rid}@{domain}` | `$MAILGUN_LIST_PREFIX` |
| `/v1/mailgun-email-list-members` | GET | `lists/{rid}@{domain}/members/pages` | `$MAILGUN_LIST_PREFIX` |
| `/v1/mailgun-email-list-member` | GET | `lists/{rid}@{domain}/members` | `$MAILGUN_MEMBER_ID` |
| `/v1/mailgun-email` | POST | `messages` |  |
| `/v1/postmark-domains` | GET | `domains` |  |
| `/v1/postmark-status` | GET | `domains` (status resource) |  |
| `/v1/postmark-templates` | GET | `templates` |  |
| `/v1/postmark-email` | POST | `email` |  |
| `/v1/quickbooks-companyinfo` | GET | `companyinfo/{realmId}` |  |
| `/v1/quickbooks-status` | GET | `companyinfo/{realmId}` (status resource) |  |
| `/v1/quickbooks-account` | GET | `company/{realmId}/account/{rid}` |  |
| `/v1/quickbooks-transactions` | GET | `reports/{rid}/TransactionList` | `$REPORT_ID` |
| `/v1/quickbooks-invoices` | GET | `company/{realmId}/invoices/{rid}` |  |
| `/v1/quickbooks-paid-invoices` | GET | `PaidInvoices` |  |
| `/v1/quickbooks-purchase-orders` | GET | `PurchaseOrders` |  |
| `/v1/quickbooks-payments` | GET | `Payments` |  |
| `/v1/timely-projects` | GET, POST | `projects` |  |
| `/v1/timely-time` | GET, PATCH | `events` |  |
| `/v1/timely-project-time` | GET, POST | `projects/{rid}/events` | `$TIMELY_PROJECT_ID` |
| `/v1/timely-project-tasks` | GET, POST | `projects/{rid}` | `$TIMELY_PROJECT_ID` |
| `/v1/timely-tasks` | GET | `labels` |  |
| `/v1/timely-users` | GET | `users` |  |
| `/v1/timely-accounts` | GET | `accounts` |  |
| `/v1/timely-status` | GET | `accounts` (status resource) |  |
| `/v1/timely-contacts` | GET | `clients` |  |
| `/v1/xero-connections` | GET | `connections` |  |
| `/v1/xero-status` | GET | `connections` (status resource) |  |
| `/v1/xero-projects` | GET, POST | `projects` |  |
| `/v1/xero-users` | GET | `projectsusers` |  |
| `/v1/xero-contacts` | GET | `Contacts` |  |
| `/v1/xero-payments` | GET | `Payments` |  |
| `/v1/xero-invoices` | GET, POST | `Invoices` |  |
| `/v1/xero-online-invoices` | GET | `Invoices/{rid}/OnlineInvoice` | `$XERO_INVOICE_ID` |
| `/v1/xero-linked-transactions` | GET | `LinkedTransactions` |  |
| `/v1/xero-inventory` | GET | `Items` |  |
| `/v1/xero-project-tasks` | GET, POST | `projects/{rid}/tasks` | `$XERO_PROJECT_ID` |
| `/v1/xero-project-time` | GET, POST | `projects/{rid}/time` | `$XERO_PROJECT_ID` |

## Data

### Responses

Every route answers with a JSON object (sorted keys, two-space indent). The HTTP status
is the object's `status_code` (default 200), and the body carries `status`, the matching
reason phrase (`"OK"`, `"Unauthorized"`, …), instead of the code.

A resource response has these keys:

- `ok`: `true` when the upstream status was 2xx.
- `result`: the list of items found at the resource's `resultKey` in the upstream JSON
  (`[]` on failure). When the resource lists `fields`, each item keeps only those fields
  (dotted paths such as `rate.value` are allowed).
- `message`: an error message, when there is one.

An unhandled exception is returned as
`{"result": "<ExceptionName>", "status": "<reason phrase>"}` with its HTTP status (500
for non-HTTP errors).

### Derivation rules

Applied to each resource when routes are built (`app/route_helpers.py`):

- `resourcePath` defaults to `resourceId`; `resultKey` defaults to `result`.
- The date window ends at `end` (parsed with `datefmt`, default `%Y-%m-%d`) or today,
  and starts `days` earlier (default 90). `start`/`end` are sent under the names in the
  auth's `paramMap` (default `start`/`end`).
- `idField` defaults to the first field ending in `_id` or `Id`, else `id`; `nameField`
  defaults to the first field ending in `name`, else `name`.
- Resources with `hidden: true` get no route of their own; a hidden status resource is
  reachable only as `<prefix>-status`.

### Token storage

Tokens live in the Flask cache under `<prefix>_access_token`, `<prefix>_refresh_token`,
`<prefix>_created_at`, `<prefix>_expires_at`, `<prefix>_realm_id`, `<prefix>_state`, and
`<prefix>_attrs`. The cache is redis or memcache when a production server is detected or
`DEBUG_MEMCACHE` is set (on in every mode except `Development`, `Ngrok`, and `Test`),
and the filesystem (`.cache/`) otherwise. Entries expire after `CACHE_DEFAULT_TIMEOUT`:
24 hours by default, 8 hours in `Development`, 1 hour in `Test`.

## Usage

1. Create and activate a virtual environment. The code needs Python 3.9 or later
   (`runtime.txt` pins 3.8.11, which cannot load it):

   `Mac`

    ```bash
    virtualenv env
    source env/bin/activate
    ```

   `Windows`

    ```bash
    virtualenv env
     ./env/Scripts/activate
    ```

2. Install requirements:

    ```bash
    pip install -r requirements.txt
    ```

3. Run the service:

    ```bash
    ./manage.py run
    ```

   `-m/--config-mode` picks the config class: `Development` (default), `Production`,
   `Custom`, `Heroku`, `Ngrok`, or `Test`. `-v` (repeatable) raises and `-q` lowers log
   verbosity. `./manage.py serve` only prints a deprecation notice. This command
   currently fails before serving; see [Known issues](#known-issues).

   The Procfile's `gunicorn app:create_app(config_mode='Custom')` builds the app without
   the provider, home, `ipsum`, or `memoization` routes, because those are only added by
   `./manage.py run`.

4. If you are contributing to this repo, install dev-requirements:

```bash
pip install -r dev-requirements.txt
```

## Xero Setup

Your own
[Xero](https://developer.xero.com/documentation/getting-started/getting-started-guide)
API account is required.

## Headless Setup

When a provider auth sets `headless: true` and `headlessElements`, and has a username
and password, an expired token with no refresh token is meant to be renewed by driving
the provider's login page in headless Chromium through
[Playwright](https://playwright.dev/python/). Xero and Timely define `headlessElements`,
but no shipped provider sets `headless`, so the fallback is off. Each `headlessElements`
entry names a CSS `selector` to fill (`content`), click (`action`), or prompt for
(`prompt`, e.g. a 2FA code). Screenshots of each step are saved to `screenshots/` in
debug mode.

## API Docs

- [Timely](https://dev.timelyapp.com/)
- [Xero Projects](https://developer.xero.com/documentation/projects/projects)

## Configuration

Application settings:

Environment Variable | Description
---------------------|------------
API_SECRET | Flask app secret key (random per process if unset; required in production)
MAILGUN_DOMAIN | Mailgun domain for error emails (required in production)
MAILGUN_SMTP_PASSWORD | Mailgun SMTP password for error emails (required in production)
DATABASE_URL, REDIS_URL, MEMCACHIER_SERVERS, REDISTOGO_URL | Any one of these marks a production server (enables Talisman HTTPS and the redis/memcache cache)
STAGE | Use the `-stage` server name

Provider credentials and pinned ids are `"$NAME"` placeholders in
`app/providers/*.json`. Each is read from the environment when routes are built; a
missing variable logs an `Env ... not found in environment!` error and leaves the value
as `None`. The variables, by provider:

Provider | Environment variables
---------|----------------------
Airtable | `AIRTABLE_PAT` (personal access token), `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_ID` (pinned ids), `AIRTABLE_WEBHOOK_SECRET`
Cloze | `CLOZE_EMAIL`, `CLOZE_API_KEY`
GitHub | `GITHUB_CLIENT_ID`, `GITHUB_SECRET`, `GITHUB_PAT`, `GITHUB_WEBHOOK_SECRET`
Gusto | `GUSTO_CLIENT_ID`, `GUSTO_SECRET`, `GUSTO_COMPANY_ID` (pinned id)
KeyCDN | `KEYCDN_API_KEY`, `KEYCDN_ZONE_ID` (pinned id)
Mailgun | `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_LIST_PREFIX`, `MAILGUN_MEMBER_ID` (pinned ids), `ADMIN_EMAIL`, `ADMIN_NAME`
Postmark | `POSTMARK_SERVER_TOKEN`, `POSTMARK_ACCOUNT_TOKEN`, `ADMIN_EMAIL`, `ADMIN_NAME`
QuickBooks | `QB_CLIENT_ID`, `QB_CLIENT_SECRET`, `QB_REALM_ID`, `QB_SANDBOX_CLIENT_ID`, `QB_SANDBOX_CLIENT_SECRET`, `QB_SANDBOX_REALM_ID`, `REPORT_ID` (pinned id)
Timely | `TIMELY_CLIENT_ID`, `TIMELY_SECRET`, `TIMELY_ACCOUNT_ID`, `TIMELY_PROJECT_ID` (pinned id); headless login (fallback off): `TIMELY_USERNAME`, `TIMELY_PASSWORD`, `GOOGLE_USERNAME`, `GOOGLE_PASSWORD`
Xero | `XERO_CLIENT_ID`, `XERO_SECRET`, `XERO_INVOICE_ID`, `XERO_PROJECT_ID` (pinned ids), `XERO_WEBHOOK_SECRET`; headless login (fallback off): `XERO_USERNAME`, `XERO_PASSWORD`
Heroku, Stripe (not loaded) | `HEROKU_WEBHOOK_SECRET`, `STRIPE_WEBHOOK_SECRET`

The `*_WEBHOOK_SECRET` values are only used by the unwired webhook code. `.env.example`
lists a subset of these and some names the code does not read (for example
`AIRTABLE_API_KEY`, where `airtable.json` reads `AIRTABLE_PAT`).

We use python-dotenv to manage environment variables. To access the values to the
environment variables above, you need to create a symbolic link (symlink) to the `.env`
file.

To create a symlink:

`Windows`

- Open a Command Prompt (right click and `Run as Administrator`)
- run the following code with the correct paths

    ```bash
    mklink "C:\{path_to_project}\\.env" "C:\{path_to_nerevu_dropbox}\Security\{username}\nerevu-api-env"
    ```

You can read more in
[How to create symbolic links in Windows 10](https://www.maketecheasier.com/create-symbolic-links-windows10/).

`Linux`

- Open a Terminal
- run the following code with the correct paths to create a soft link

    ```bash
    ln -s /{path_to_nerevu_dropbox}/Security/{username}/nerevu-api-env /{path_to_project}/.env
    ```

## Headless browser

The headless login uses Playwright's Chromium, not chromedriver. To use it once a
provider sets `headless: true`, after installing the requirements (which include
`playwright`), download the browser:

```bash
playwright install chromium
```

## Known issues

- Importing the `app` package raises `ImportError`: `app/routes/webhook.py:20` imports
  `BaseView` from `app.routes`, but `BaseView` is defined in `app/routes/auth.py:71`.
  The import runs through `app/__init__.py:187` → `app/routes/api.py:21`, so
  `./manage.py` and the Procfile's gunicorn both fail at startup.
- `./manage.py` ends with `manager.run()` (`manage.py:478`), but `manager` is a click
  group, which has no `run` method, so running the script raises `AttributeError`.
- The code needs Python 3.9+ (`list[str]` in a class body at `app/routes/auth.py:75`),
  but `runtime.txt` pins `python-3.8.11`.
- Resource routes only implement `GET` (`APIResource.get`, `app/routes/auth.py:546`).
  `POST`, `PATCH`, and `DELETE`, routed from a resource's `methods`, fail with Flask's
  "Unimplemented method" assertion (500).
- The auth route is registered for `GET` only because the `auth` entry has no `methods`
  (`app/api_configs/default.json:25-29`, `app/routes/api.py:53`), so `Auth.patch` and
  `Auth.delete` (`app/routes/auth.py:305`, `:309`) are unreachable.
- Webhooks are never routed: `create_webhook_routes` (`app/routes/api.py:153`) has no
  caller and looks up a `<Prefix>Hook` class that `app/routes/webhook.py` does not
  define.
- Request parameters are ignored on resource routes: `PatchedMethodView.kwargs` parses
  the request only when the request path equals `/v1/<prefix>-api-resource`
  (`app/routes/__init__.py:53`, `:64`), which no resource route matches.
- `/v1/memoization` fails on every request: `create_method_view_route` passes
  `resource=` and `provider=` to `Memoization`, whose constructor only accepts `prefix`
  (`app/routes/api.py:119-127`, `app/routes/__init__.py:38-40`). Its `<path>` URL
  segment is also never added because `params` is not forwarded
  (`app/routes/api.py:119-127`).
