# HTTPSanction

HTTPSanction is a Flask-based HTTP authentication service that centralizes OAuth and API authentication for multiple third-party providers. It exposes a versioned REST API (`/v1/`) and handles token management, caching, webhook ingestion, and headless browser flows for services that require them.

**Supported providers:** Airtable, Cloze, GitHub, Gusto, Heroku, KeyCDN, Mailgun, Postmark, QuickBooks, Stripe, Timely, Xero

## Examples

All endpoints are served under the `/v1` prefix. The home route (`GET /` or `GET /v1`) returns a JSON index of every available route.

### Authenticate a provider

Visiting the auth URL for a provider initiates the OAuth flow. If the token is already valid it returns the current status instead of redirecting.

```bash
# Start OAuth flow (redirects to the provider's consent screen)
curl http://localhost:5000/v1/xero-auth

# Check Timely auth status
curl http://localhost:5000/v1/timely-auth
```

### Fetch a resource collection

```bash
# List all Xero projects
curl http://localhost:5000/v1/xero-projects

# List all Timely time entries
curl http://localhost:5000/v1/timely-time

# List Xero invoices
curl http://localhost:5000/v1/xero-invoices
```

### Fetch a single resource by ID

```bash
# Get a specific Xero contact
curl http://localhost:5000/v1/xero-contacts/<ContactID>

# Get a specific Timely user
curl http://localhost:5000/v1/timely-users/<userId>
```

### Create a resource

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

```bash
# Force token refresh
curl -X PATCH http://localhost:5000/v1/xero-auth

# Revoke token
curl -X DELETE http://localhost:5000/v1/xero-auth
```

### Receive webhooks

Providers that support webhooks POST events to a dedicated endpoint. The service verifies the signature and processes the payload.

```bash
# Xero webhook endpoint (configure this URL in your Xero developer portal)
POST http://localhost:5000/v1/xero
```

## Usage

1. Create and activate a virtual environment:

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

2. Install requirements::

    ```bash
    pip install -r requirements.txt
    ```

3. Run the service:

    ```bash
    bin/sync-time
    ```

4. If you are contributing to this repo, install dev-requirements::

```bash
pip install -r dev-requirements.txt
```

## Xero Setup

Your own [Xero](https://developer.xero.com/documentation/getting-started/getting-started-guide) API account is required.

## Headless Setup

https://sites.google.com/a/chromium.org/chromedriver/home

## API Docs

- [Timely](https://dev.timelyapp.com/)
- [Xero Projects](https://developer.xero.com/documentation/projects/projects)

## Configuration

Environment Variable | Description
---------------------|------------
API_SECRET | Flask App secret key
TIMELY_CLIENT_ID | Timely API client ID
TIMELY_SECRET | Timely API secret
XERO_CLIENT_ID | Xero API client ID
XERO_SECRET | Xero API secret

We use python-dotenv to manage environment variables. To access the values to the environment variables above, you need to create a symbolic link (symlink) to the `.env` file.

To create a symlink:

`Windows`

- Open a Command Prompt (right click and `Run as Administrator`)
- run the following code with the correct paths

    ```bash
    mklink "C:\{path_to_project}\\.env" "C:\{path_to_nerevu_dropbox}\Security\{username}\nerevu-api-env"
    ```

You can read more about symlinks [here](https://www.maketecheasier.com/create-symbolic-links-windows10/).

`Linux`

- Open a Terminal
- run the following code with the correct paths to create a soft link

    ```bash
    ln -s /{path_to_nerevu_dropbox}/Security/{username}/nerevu-api-env /{path_to_project}/.env
    ```

## Chrome driver

`Macports`

`sudo port install chromedriver`

`Homebrew`

`brew install chromedriver`

`Download`

[chromium.org](https://sites.google.com/a/chromium.org/chromedriver/downloads)
