---
source: ../../../../webhooks/README.md
---

# Nerevu Webhooks

A Flask-based webhook receiver meant to validate incoming webhook payloads from
third-party providers (Heroku, Xero, Stripe, GitHub) and route them to handler
functions. As shipped, the provider lookup never finds its configuration, so every
webhook `POST` that does not carry its own provider configuration in the query string
returns `400 Invalid provider` (see [Known issues](#known-issues)).

## How it works

Webhooks are received at `POST /v1/webhooks/<provider>/<func_name>`. The
`Webhooks` view in `app/api.py`:

1. Builds its keyword arguments from the request's query string, then fills in the
   whitelisted config keys (`WEBHOOKS`, `DISTRIBUTION_ID`, `CHUNK_SIZE`, `ROW_LIMIT`;
   `ERR_LIMIT` is whitelisted but not defined) under **lowercased** names
   (`app/utils.py:385-393`). Query-string values are parsed with `ast.literal_eval`, so
   a query argument can be a dict.
2. Looks up the provider's settings with the **uppercase** key `WEBHOOKS`
   (`app/api.py:118`). The config value is stored as `webhooks`, so the lookup comes
   back empty and the view returns `400 {"message": "Invalid provider: <provider>"}`.
   The only way to reach the next steps is to pass a `WEBHOOKS` query argument, which
   the view then uses as the provider configuration in place of `config.py`.
3. Checks the request signature with the provider's settings (`check_signature`,
   `app/utils.py:399-420`). If the provider settings contain a truthy
   `ignore_signature`, no check is made. Because the settings can come from the
   query string (step 2), the caller can turn signature checking off, and can also
   supply its own `webhook_secret`. A failed check returns `401 Invalid signature`.
4. Reads the JSON body and takes the value under the provider's `payload_key`. A
   missing value returns `400 Invalid payload`.
5. Calls `getattr(app.hooks, func_name)(value, **provider_settings)`. Any attribute
   of the `app.hooks` module is reachable this way, including its imports
   (`boto3`, `dt`, `Config`, `session`, `client`), not just the handler functions.
   An unknown name returns `400 Invalid function: <func_name>`.

On success the response is an empty `text/plain` `200`: the handler's return value
is discarded (`app/api.py:135-137`, `app/utils.py:84-90`). Error responses are
JSON objects with `message` and `status`, where `status` is the HTTP reason phrase
(for example `"Bad Request"`), not the numeric code (`app/utils.py:85`).

## Setup

1. Create and activate a virtual environment (`runtime.txt` pins Python 3.8.3;
   `.travis.yml` tests 3.6, 3.7, 3.8 and pypy3.6):

    ```bash
    python -m venv env
    source env/bin/activate  # Mac/Linux
    ./env/Scripts/activate   # Windows
    ```

2. Install dependencies:

    ```bash
    pip install -r requirements.txt
    ```

3. Create a `.env` file in the project root (see [Configuration](#configuration))

4. Run the development server:

    ```bash
    python manage.py run
    ```

   The API will be available at `http://localhost:5000/v1`.

`app/hooks.py` builds a boto3 session and a CloudFront client when the module is
imported (`app/hooks.py:15-26`), and `app/api.py` imports it, so the AWS settings
are read every time the app starts, in every config mode. The session uses the
`nerevu` AWS profile if it exists and falls back to `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY` and `AWS_REGION` otherwise.

## Usage

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Redirects to `/v1` |
| `GET` | `/v1` | API home and link index (cached for 3 hours) |
| `GET` | `/v1/ipsum` | Random sentence (health check; cached for 3 hours) |
| `GET` | `/v1/webhooks/<provider>/<func_name>` | Describe a webhook route |
| `POST` | `/v1/webhooks/<provider>/<func_name>` | Receive a webhook (returns `400` as shipped; see [How it works](#how-it-works)) |
| `GET` | `/v1/memoization` | Stub: returns a "route is not yet complete" message |
| `DELETE` | `/v1/memoization` | Clear the whole cache |

The `/v1/memoization/<path>` form is not registered (see
[Known issues](#known-issues)), so only clearing the whole cache is available.
Neither memoization route requires authentication.

### Webhook Example

To trigger the `invalidate_cloudfront` function via a Heroku webhook:

```bash
curl -X POST http://localhost:5000/v1/webhooks/heroku/invalidate_cloudfront \
  -H "Content-Type: application/json" \
  -d '{"action": "update"}'
```

As shipped this returns `400` with the message `Invalid provider: heroku`, because
the provider settings are never found (step 2 above). With the settings reachable,
the Heroku entry has `ignore_signature: True`, so no `Heroku-Webhook-Hmac-SHA256`
header is needed or checked. A provider that does check signatures, such as `xero`,
expects its header (`x-xero-signature`) to hold the base64 HMAC-SHA256 of the raw
request body keyed with the provider's secret.

`invalidate_cloudfront` acts only when the payload value is `"update"` and then
invalidates these fixed paths: `/icons/*.svg`, `/images*`, `/favicon.*`, `/*.json`
(`app/hooks.py:31-50`). It takes the distribution from a `distribution_id` key in
the provider settings. No provider in `config.py` has that key, and the
`CF_DISTRIBUTION_ID` value (`Config.DISTRIBUTION_ID`) is never passed to the hook,
so the invalidation is requested with an empty distribution id.

### Adding a Hook

Define a new function in `app/hooks.py`:

```python
def my_handler(value, **kwargs):
    # value is the payload's `payload_key` entry; kwargs are the provider settings
    # the return value is discarded: the route answers with an empty 200
    return {"message": "handled!"}
```

Then call it via `POST /v1/webhooks/<provider>/my_handler`.

Hooks in `app/hooks.py`:

| Hook | State |
|------|-------|
| `invalidate_cloudfront` | Creates a CloudFront invalidation when the value is `"update"`; receives an empty distribution id (see above) |
| `send_subscription_notification` | Raises `NameError` on the first new-invoice event: `get_invoice`, `requests` and `postmark_url` are not defined in the module (`app/hooks.py:57,61,100`) |

### Supported Providers

Provider settings live in `Config.WEBHOOKS` (`config.py:114-143`):

| Provider | `signature_header` | `digest` | Encoding | `payload_key` | `ignore_signature` |
|----------|-------------------|----------|----------|---------------|--------------------|
| `heroku` | `Heroku-Webhook-Hmac-SHA256` | `sha256` | base64 | `action` | `True` (signature not checked) |
| `xero` | `x-xero-signature` | `sha256` | base64 | `events` | `False` |
| `stripe` | `HTTP_STRIPE_SIGNATURE` | `sha1` | hex, `split_signature` | none | not set |
| `github` | `???` | `sha1` | hex, `split_signature` | none | not set |

Only `xero` actually checks a signature; `heroku` skips it. `stripe` and `github`
cannot work: they have no `payload_key`, `HTTP_STRIPE_SIGNATURE` is a WSGI environ
name rather than an HTTP header name, github's header is the literal `???`, and the
`split_signature` path fails (see [Known issues](#known-issues)). For any provider
that checks signatures, a request without the signature header raises an error
(HTTP 500) instead of returning `401`.

## Configuration

Create a `.env` file in the project root with the following variables:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask secret key (random per process if unset) |
| `AWS_ACCESS_KEY_ID` | AWS access key (used when there is no `nerevu` AWS profile) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key (used when there is no `nerevu` AWS profile) |
| `AWS_REGION` | AWS region (used when there is no `nerevu` AWS profile) |
| `CF_DISTRIBUTION_ID` | CloudFront distribution ID; read into `Config.DISTRIBUTION_ID` but never reaches the hook |
| `HEROKU_WEBHOOK_SECRET` | Heroku webhook signing secret (unused while `ignore_signature` is `True`) |
| `XERO_WEBHOOK_SECRET` | Xero webhook signing secret |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `GITHUB_WEBHOOK_SECRET` | GitHub webhook signing secret |
| `STAGE` | Set on a staging server; adds `-stage` to the server name |
| `MAILGUN_SMTP_PASSWORD` | If set, `manage.py` emails error logs through Mailgun SMTP (`MAILGUN_DOMAIN`, `MAILGUN_SMTP_SERVER`, `MAILGUN_SMTP_PORT`, `MAILGUN_SMTP_LOGIN` are also read) |

`.env.example` lists `WEBHOOK_SECRET`, which `config.py` never reads; the secrets
are the four provider-specific `*_WEBHOOK_SECRET` variables above. The AWS keys are
listed in `REQUIRED_PROD_SETTINGS`, but a missing one is only logged at startup.

Config modes (`config.py`), selected with `-m`:

| Mode | Notes |
|------|-------|
| `Development` (default) | Debug on; filesystem cache unless a production server is detected; cache timeout 8 hours |
| `Test` | Debug and testing on; filesystem cache unless a production server is detected; cache timeout 1 hour |
| `Production` | Binds `0.0.0.0`; Talisman HTTPS enforcement when a production server is detected; cache type from `mezmorize` |
| `Heroku` | `Production` with `SERVER_NAME` `webhooks[-stage].herokuapp.com` when a production server is detected |
| `Custom` | `Production` with `SERVER_NAME` `webhooks[-stage].nerevu.com` when a production server is detected (used by the `Procfile`) |

A production server is detected when any of `DATABASE_URL`, `REDIS_URL`,
`MEMCACHIER_SERVERS` or `REDISTOGO_URL` is set (`config.py:36,40`).

## Development

```bash
# Run with a specific config mode (Development is default)
python manage.py -m Development run

# Run tests (nose)
python manage.py test

# Lint (flake8; add --strict for pylint)
python manage.py lint

# Format code (black)
python manage.py prettify

# Lint staged changes (helpers/check-stage)
python manage.py check

# List commands
python manage.py help
```

`python manage.py serve` only prints a deprecation notice; use `run`.

## Deployment

```bash
# Push the features branch to origin (staging)
python manage.py deploy

# Push the master branch to origin (production)
python manage.py deploy -r production

# Add your SSH key to a Heroku remote (default: staging)
python manage.py add_keys -r production
```

`deploy` runs `git push origin features`, or `git push origin master` when
`-r production` is given; it does not push to Heroku directly.

The `Procfile` runs `gunicorn app:create_app(config_mode='Custom') -w 3 -k gevent`.
Production detection and HTTPS enforcement via Talisman require one of
`DATABASE_URL`, `REDIS_URL`, `MEMCACHIER_SERVERS` or `REDISTOGO_URL` to be set.

## Known issues

- Every webhook `POST` without a `WEBHOOKS` query argument returns `400 Invalid
  provider`: `parse_kwargs` stores the config as `webhooks` (`app/utils.py:391`)
  but the view reads `WEBHOOKS` (`app/api.py:118`). The items below apply once
  provider settings are reachable.
- Provider settings, including `webhook_secret` and `ignore_signature`, are taken
  from the query string before `config.py` (`app/utils.py:386`, `app/api.py:118`),
  so any caller can disable signature checking or choose the secret.
- Heroku signatures are never checked: the heroku entry sets
  `"ignore_signature": True` (`config.py:121`, `app/utils.py:400-401`).
- A request missing the signature header raises `AttributeError` (HTTP 500)
  instead of returning `401`, because `request.headers.get(...)` returns `None`
  before `.encode` (`app/utils.py:403`).
- `stripe` and `github` have no `payload_key`, so a request that passes the
  signature check raises `KeyError` (`app/api.py:124`, `config.py:131-142`).
- The `split_signature` path calls `bytes.split("=")`, which raises `TypeError`
  (`app/utils.py:406`).
- `HTTP_STRIPE_SIGNATURE` (`config.py:132`) is a WSGI environ key, not a header
  name, and github's header is the placeholder `"???"` (`config.py:138`).
- `func_name` resolves any attribute of `app.hooks`, not a registry of handlers
  (`app/api.py:130`).
- `send_subscription_notification` raises `NameError` for `get_invoice`,
  `requests` and `postmark_url` (`app/hooks.py:57,61,100`).
- `invalidate_cloudfront` receives an empty `distribution_id`; `CF_DISTRIBUTION_ID`
  is not part of any provider entry (`app/hooks.py:31`, `config.py:111`).
- The handler's return value is discarded and a successful dispatch returns an
  empty `text/plain` body (`app/api.py:135-137`, `app/utils.py:84-90`).
- `DELETE /v1/memoization/<path>` is never registered: the method-view option is
  spelled `"paramS"` (`app/api.py:187`) while the loop reads `"params"`
  (`app/api.py:213`). Even if registered, it would delete the key `/v1/<path>`
  (`app/api.py:171`), which matches only `/v1/ipsum` (key prefix `%s`,
  `app/api.py:82`).
- The memoization routes are unauthenticated (`app/api.py:149-179`).

## License

MIT © [Nerevu Group](https://nerevu.com)
