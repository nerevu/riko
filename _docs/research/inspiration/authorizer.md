---
source: ../../../../authorizer/README.md
---

# Nerevu API

A Flask-based OAuth authorization gateway and API proxy. It runs a provider's OAuth
flow, caches the token, and exposes the provider's API resources through a uniform REST
interface.

> **Status:** only Xero is wired up, and no view route currently answers successfully;
> see [Known issues](#known-issues). The sections below describe what the code is
> written to do.

## Supported Integrations

Only `xero` is loaded: it is the sole entry in `providerNames` in
`app/api_configs/default.json`, and `app/providers/xero.json` is the only provider
definition. Xero authenticates with OAuth2 (authorization code flow, `offline_access`
scope) and exposes the resources listed under [Resource Endpoints](#resource-endpoints).

The other integrations are present but not routed. Their settings are the `RESOURCES`,
`AUTHENTICATION`, and `WEBHOOKS` dicts in `config.py`, and
`app/providers/{aws,cloze,gsheets,quickbooks}.py` hold their client code, but nothing
reads those dicts or imports those modules for routing:

| Service | Auth type (in `config.py`) | Resources | Routed |
|---------|-----------|-----------|--------|
| Xero | OAuth2 (`app/providers/xero.json`) | Projects (routed resources: see [Resource Endpoints](#resource-endpoints)) | yes |
| Airtable | API Key | Tables | no |
| AWS | Boto | CloudFront distributions | no |
| Cloze | API Key | People, project stages | no |
| Google Sheets | Service account | Worksheets | no |
| Gusto | OAuth2 | Companies, employees, payrolls | no |
| KeyCDN | Basic auth | Zones, cache purge | no |
| Mailgun | API Key | Domains, email lists, send email | no |
| Postmark | API Token | Domains, templates, send email | no |
| QuickBooks | OAuth2 | Transactions, reports | no |
| Timely | OAuth2 | Projects, tasks, time entries | no |

## Setup

1. Create and activate a virtual environment. The code needs Python 3.9 or later
   (`runtime.txt` pins 3.8.11, which cannot load it):

    ```bash
    python -m venv env
    source env/bin/activate       # Mac/Linux
    ./env/Scripts/activate        # Windows
    ```

2. Install requirements:

    ```bash
    pip install -r requirements.txt
    ```

3. Create a `.env` file (or symlink to one) with credentials for the services you use.
   Only the Flask and Xero values are read by the live code today; the rest feed the
   unrouted integrations (see [Configuration Reference](#configuration-reference)):

    ```bash
    # Flask
    API_SECRET=your-secret-key

    # Xero (routed)
    XERO_CLIENT_ID=...
    XERO_SECRET=...

    # QuickBooks (not routed)
    QB_CLIENT_ID=...
    QB_CLIENT_SECRET=...

    # Timely (not routed)
    TIMELY_CLIENT_ID=...
    TIMELY_SECRET=...

    # Gusto (not routed)
    GUSTO_CLIENT_ID=...
    GUSTO_SECRET=...
    GUSTO_COMPANY_ID=...

    # Airtable (not routed)
    AIRTABLE_API_KEY=...
    AIRTABLE_TABLE=...

    # Cloze (not routed)
    CLOZE_API_KEY=...

    # Google Sheets (not routed)
    GSHEETS_SHEETNAME=...
    GSHEETS_SHEET_ID=...
    GSHEETS_WORKSHEET_NAME=...

    # AWS (not routed)
    AWS_ACCESS_KEY_ID=...
    AWS_SECRET_ACCESS_KEY=...
    CLOUDFRONT_DISTRIBUTION_ID=...

    # KeyCDN (not routed)
    KEYCDN_API_KEY=...

    # Mailgun (SMTP values also used for error emails in production)
    MAILGUN_API_KEY=...
    MAILGUN_DOMAIN=...
    MAILGUN_SMTP_PASSWORD=...

    # Postmark (not routed)
    POSTMARK_ACCOUNT_TOKEN=...
    POSTMARK_SERVER_TOKEN=...
    ```

   To symlink to a shared secrets file:

    ```bash
    # Mac/Linux
    ln -s /path/to/secrets/.env /path/to/project/.env

    # Windows (run as Administrator)
    mklink "C:\path\to\project\.env" "C:\path\to\secrets\.env"
    ```

4. Run the server:

    ```bash
    python manage.py run
    ```

   `-m/--config-mode` picks the config class: `Development` (default), `Production`,
   `Custom`, `Heroku`, `Ngrok`, or `Test`; `-v` (repeatable) raises log verbosity. The
   API is meant to be available at `http://localhost:5000/v1/`, but this command
   currently fails before serving; see [Known issues](#known-issues).

   The provider, home, `ipsum`, and `memoization` routes are only added by
   `manage.py run`. The Procfile's `gunicorn app:create_app(config_mode='Custom')`
   builds the app without them.

## Usage

### OAuth Authorization

Navigate to the auth endpoint to start the OAuth flow:

```text
GET /v1/xero-auth
```

If the cached token is valid, the route returns the status resource with the token,
`state`, `realm_id`, and the Xero `tenant_id` (read from `result[0].tenantId` of the
connections response). Otherwise it redirects to Xero's consent screen. An optional
`callback_url` query parameter is cached for the callback.

The callback is handled at:

```text
GET /v1/xero-callback
```

`PATCH /v1/xero-auth` renews the token and redirects to the auth route. There is no
revoke route: the auth route accepts only `GET` and `PATCH`.

### Resource Endpoints

The intended interface is a uniform CRUD surface per provider resource:

```text
GET    /v1/{provider}-{resource}           # list or fetch resource
GET    /v1/{provider}-{resource}/{id}      # fetch by ID
POST   /v1/{provider}-{resource}           # create
PATCH  /v1/{provider}-{resource}/{id}      # update
DELETE /v1/{provider}-{resource}/{id}      # delete
```

As routed today, each Xero resource gets one route, `/v1/xero-<resourceId>` with
underscores turned into dashes, plus `/v1/xero-status` for the status resource
(`connections`). There is no `/{id}` URL segment. Methods come from the resource's
`methods` in `xero.json` (default `GET`); `DELETE` is never routed.

| Route | Methods | Upstream path |
| --- | --- | --- |
| `/v1/xero-connections` | GET | `connections` |
| `/v1/xero-status` | GET | `connections` (status resource) |
| `/v1/xero-projects` | GET, POST | `projects` |
| `/v1/xero-users` | GET | `projectsusers` |
| `/v1/xero-contacts` | GET | `Contacts` |
| `/v1/xero-payments` | GET | `Payments` |
| `/v1/xero-invoices` | GET, POST | `Invoices` |
| `/v1/xero-online-invoices` | GET | `Invoices/{rid}/OnlineInvoice` |
| `/v1/xero-linked-transactions` | GET | `LinkedTransactions` |
| `/v1/xero-inventory` | GET | `Items` |
| `/v1/xero-project-tasks` | GET, POST | `projects/{rid}/tasks` |
| `/v1/xero-project-time` | GET, POST | `projects/{rid}/time` |

Upstream paths are relative to the auth's `apiBaseURL` (`https://api.xero.com`,
`…/api.xro/2.0`, or `…/projects.xro/2.0`). The Xero auth declares a
`Xero-tenant-id: {tenant_id}` header for all requests.

Request parameters come from the query string, form, or JSON body; use snake_case names
(camelCase keys are hyphenated and then ignored):

| Parameter | Effect |
| --- | --- |
| `rid` | Item id; for resources with a sub-resource (`online_invoices`, `project_tasks`, `project_time`), the parent id that fills `{rid}` (required there) |
| `id` | Item id appended to the URL (for sub-resources, the sub-item id) |
| `dry_run` | Return the request data without calling Xero |
| `use_default` | Return a single item (at `pos`) instead of the collection |
| `pos` | Position of the item to return with `use_default` (default 0) |
| `dictify` | Key cached data by id |
| `end` | Last date of the date window |

`POST` and `PATCH` are meant to send the remaining request values as the upstream body,
but both raise `TypeError` before sending (see [Known issues](#known-issues)).

Examples:

```bash
# Check Xero auth status
curl http://localhost:5000/v1/xero-status

# List Xero projects
curl http://localhost:5000/v1/xero-projects

# List Xero contacts
curl http://localhost:5000/v1/xero-contacts

# List the tasks of one Xero project
curl "http://localhost:5000/v1/xero-project-tasks?rid=<projectId>"
```

Examples for the unrouted integrations (intended; these routes are not registered
today):

```bash
# Check QuickBooks auth status
curl http://localhost:5000/v1/qb-status

# List Timely projects
curl http://localhost:5000/v1/timely-projects

# List Cloze pipeline stages
curl http://localhost:5000/v1/cloze-stages

# Fetch a Timely time entry
curl http://localhost:5000/v1/timely-time/12345
```

The home route (`GET /` or `GET /v1`) returns a JSON index of all routes, and
`GET /v1/ipsum` returns a random sentence.

## Data

### Responses

Every route answers with a JSON object (sorted keys, two-space indent). The HTTP status
is the object's `status_code` (default 200), and the body carries `status`, the matching
reason phrase, instead of the code. Resource responses carry:

- `ok`: `true` when the upstream status was 2xx.
- `result`: the items under the resource's `subkey` in the upstream JSON (for example
  `items` for projects, `Contacts` for contacts). When the resource lists `fields`, each
  item keeps only those fields.
- `message`: an error message, when there is one.
- `links`: the route index, on `POST` responses.

An unhandled exception is returned as
`{"result": "<ExceptionName>", "status": "<reason phrase>"}` with its HTTP status (500
for non-HTTP errors).

### Derivation rules

- `idField` defaults to the first field containing `id`, else `id`; `nameField` to the
  first field containing `name`, else `name`.
- `end` defaults to the date the process started (the default is evaluated once at
  import), formatted with `datefmt` (default `%Y-%m-%d`).
- Any auth value starting with `$` is replaced by that environment variable
  (`app/routes/api.py:154-162`).
- Tokens are cached under `xero_access_token`, `xero_refresh_token`, `xero_created_at`,
  `xero_expires_at`, `xero_realm_id`, `xero_tenant_id`, and `xero_state`. The cache is
  redis or memcache when a production server is detected or `DEBUG_MEMCACHE` is set (on
  in every mode except `Development`, `Ngrok`, and `Test`), and the filesystem
  otherwise. Entries expire after 24 hours by default, 8 hours in `Development`, 1 hour
  in `Test`.

## Development

Install dev dependencies:

```bash
pip install -r dev-requirements.txt
```

There are no tests: `python manage.py test` exits with "Not implemented!".

Lint (flake8 and eslint; `--strict` adds pylint):

```bash
python manage.py lint
```

Other `manage.py` commands:

| Command | Does |
| --- | --- |
| `run` | Register routes and start the dev server |
| `prettify` | Format code with black and isort, and JSON |
| `check` | Run `helpers/check-stage` on staged changes |
| `schema-to-code -s <schema>` | Generate Python classes from a JSON schema (default `provider`) |
| `validate-schema -s <schema>` | Validate the JSON schemas (default `all`) |
| `validate-data -s <schema>` | Validate provider and config JSON against their schemas (default `all`) |
| `test-oauth -m <method> -r <resource> -p <project id>` | Call the Xero API directly (`time`, `task`, `project`, `contact`) |
| `deploy -r <remote>` | `git push origin` to `master` (production) or `features` |
| `add-keys -r <remote>` | Add your SSH key to a Heroku remote |
| `require` | Rebuild `base-requirements.txt` from `pip freeze` |

The `bin/` scripts (`sync-time`, `store-*`, `prune-mappings`, …) call `manage sync`,
`manage store`, and `manage prune`, which this `manage.py` does not define.

## Configuration Reference

Variables the live code reads:

| Variable | Description |
|----------|-------------|
| `API_SECRET` | Flask app secret key (random per process if unset; required in production) |
| `XERO_CLIENT_ID` / `XERO_SECRET` | Xero OAuth2 credentials (`clientId`/`clientSecret` in `xero.json`) |
| `XERO_USERNAME` / `XERO_PASSWORD` | Xero login for the headless (Selenium/Chrome) fallback; nothing sets the auth's `headless` flag, so the fallback is off |
| `MAILGUN_DOMAIN` / `MAILGUN_SMTP_PASSWORD` | Mailgun SMTP for error emails (required in production) |
| `DATABASE_URL`, `REDIS_URL`, `MEMCACHIER_SERVERS`, `REDISTOGO_URL` | Any one marks a production server |
| `STAGE` | Use the `-stage` server name |

`xero.json` also references `XERO_WEBHOOK_SECRET` in its `webhook` block, but no webhook
route is registered and only auth values are resolved from the environment, so it is not
read.

Variables for the unrouted integrations, read only by the `config.py` dicts that nothing
routes:

| Variable | Description |
|----------|-------------|
| `QB_CLIENT_ID` / `QB_CLIENT_SECRET` | QuickBooks OAuth2 credentials |
| `TIMELY_CLIENT_ID` / `TIMELY_SECRET` | Timely OAuth2 credentials |
| `GUSTO_CLIENT_ID` / `GUSTO_SECRET` | Gusto OAuth2 credentials |
| `GUSTO_COMPANY_ID` | Gusto company ID |
| `AIRTABLE_API_KEY` / `AIRTABLE_TABLE` | Airtable credentials |
| `CLOZE_API_KEY` | Cloze API key |
| `GSHEETS_SHEETNAME` / `GSHEETS_SHEET_ID` / `GSHEETS_WORKSHEET_NAME` | Google Sheets config |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS credentials |
| `CLOUDFRONT_DISTRIBUTION_ID` | AWS CloudFront distribution |
| `KEYCDN_API_KEY` | KeyCDN API key |
| `MAILGUN_API_KEY` | Mailgun API key |
| `MAILGUN_LIST_PREFIX` | Prefix for Mailgun mailing lists |
| `POSTMARK_ACCOUNT_TOKEN` / `POSTMARK_SERVER_TOKEN` | Postmark credentials |

## Production

The app detects production by the presence of a `DATABASE_URL`, `REDIS_URL`,
`MEMCACHIER_SERVERS`, or `REDISTOGO_URL` environment variable. In production,
[Talisman](https://github.com/GoogleCloudPlatform/flask-talisman) (HTTPS enforcement)
and memcache are enabled automatically.

For staging, set:

```bash
heroku config:set STAGE=true --remote staging
```

## Known issues

- Running `manage.py` raises `AttributeError`: it ends with `manager.run()`
  (`manage.py:552`), but `manager` is a click group, which has no `run` method.
- Every view route fails with `TypeError` when its view is built: `PatchedMethodView`
  calls `camel_to_snake_case("-", ...)` (`app/routes/__init__.py:49`), but
  `camel_to_snake_case` takes one argument (`app/utils.py:490`). This covers the auth,
  callback, status, resource, and memoization routes; only `/`, `/v1`, and `/v1/ipsum`
  are plain functions.
- The code needs Python 3.9+ (`list[str]` in a class body at `app/routes/auth.py:88`),
  but `runtime.txt` pins `python-3.8.11`.
- `POST` and `PATCH` raise `TypeError`: `remove_keys(self.kwargs, black_list)` passes
  the blacklist set as a single key (`app/routes/auth.py:805`, `:866`), and meza's
  `remove_keys` puts its key arguments in a set. The body is also built from the view's
  kwargs, which hold whitelisted config values such as `secret` and `secret_key`
  (`app/routes/__init__.py:74`).
- `Auth.delete` (`app/routes/auth.py:166`) is unreachable because the auth route is
  registered for `GET` and `PATCH` only (`app/routes/api.py:54-59`).
- `/v1/memoization` gets no `<path>` segment because `create_method_view_route` does not
  forward the config's `params` (`app/routes/api.py:246-250`).
- `python manage.py test` only prints "Not implemented!" (`manage.py:341`), and
  `lint --strict` points pylint at `tests/standard.rc` (`manage.py:278`), but there is
  no `tests/` directory.
- `test-oauth` reads `app.config["XERO_OAUTH_VERSION"]` (`manage.py:256`), which no
  config class sets, so it raises `KeyError`.
- The `bin/` scripts call `manage sync`, `manage store`, and `manage prune`, which do
  not exist in `manage.py`.
