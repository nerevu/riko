# Nerevu Webhooks

A Flask-based webhook receiver that validates and routes incoming webhook payloads from third-party providers (Heroku, Xero, Stripe, GitHub) to handler functions.

## How it works

Webhooks are received at `POST /v1/webhooks/<provider>/<func_name>`. The app:

1. Validates the request signature using the provider's secret
2. Extracts the payload key configured for that provider
3. Calls `func_name` from `app/hooks.py` with the payload value

## Setup

1. Create and activate a virtual environment:

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

## Usage

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1` | API home and link index |
| `GET` | `/v1/ipsum` | Random sentence (health check) |
| `GET` | `/v1/webhooks/<provider>/<func_name>` | Describe a webhook route |
| `POST` | `/v1/webhooks/<provider>/<func_name>` | Receive a webhook |
| `DELETE` | `/v1/memoization[/<path>]` | Clear cache (all or by path) |

### Webhook Example

To trigger the `invalidate_cloudfront` function via a Heroku webhook:

```bash
curl -X POST http://localhost:5000/v1/webhooks/heroku/invalidate_cloudfront \
  -H "Content-Type: application/json" \
  -d '{"action": "update"}'
```

### Adding a Hook

Define a new function in `app/hooks.py`:

```python
def my_handler(value, **kwargs):
    # value is extracted from the payload using the provider's payload_key
    return {"message": "handled!"}
```

Then call it via `POST /v1/webhooks/<provider>/my_handler`.

### Supported Providers

| Provider | Signature Header | Digest |
|----------|-----------------|--------|
| `heroku` | `Heroku-Webhook-Hmac-SHA256` | SHA-256 |
| `xero` | `x-xero-signature` | SHA-256 |
| `stripe` | `HTTP_STRIPE_SIGNATURE` | SHA-1 |
| `github` | configurable | SHA-1 |

## Configuration

Create a `.env` file in the project root with the following variables:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask secret key |
| `AWS_ACCESS_KEY_ID` | AWS access key (required in production) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key (required in production) |
| `AWS_REGION` | AWS region (required in production) |
| `CF_DISTRIBUTION_ID` | CloudFront distribution ID |
| `HEROKU_WEBHOOK_SECRET` | Heroku webhook signing secret |
| `XERO_WEBHOOK_SECRET` | Xero webhook signing secret |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `GITHUB_WEBHOOK_SECRET` | GitHub webhook signing secret |

## Development

```bash
# Run with a specific config mode (Development is default)
python manage.py -m Development run

# Run tests
python manage.py test

# Lint
python manage.py lint

# Format code
python manage.py prettify
```

## Deployment

```bash
# Deploy to staging
python manage.py deploy

# Deploy to production
python manage.py deploy -r production
```

Heroku deployment requires `DATABASE_URL`, `REDIS_URL`, or `MEMCACHIER_SERVERS` to be set — their presence signals production mode and enables HTTPS enforcement via Talisman.

## License

MIT © [Nerevu Group](https://nerevu.com)
