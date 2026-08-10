# Nerevu API

A Flask-based OAuth authorization gateway and API proxy. It handles OAuth flows (OAuth1, OAuth2, API key, service account) for multiple third-party services and exposes a unified REST interface to interact with them.

## Supported Integrations

| Service | Auth Type | Resources |
|---------|-----------|-----------|
| Airtable | API Key | Tables |
| AWS | Boto | CloudFront distributions |
| Cloze | API Key | People, project stages |
| Google Sheets | Service account | Worksheets |
| Gusto | OAuth2 | Companies, employees, payrolls |
| KeyCDN | Basic auth | Zones, cache purge |
| Mailgun | API Key | Domains, email lists, send email |
| Postmark | API Token | Domains, templates, send email |
| QuickBooks | OAuth2 | Transactions, reports |
| Timely | OAuth2 | Projects, tasks, time entries |
| Xero | OAuth1/OAuth2 | Projects |

## Setup

1. Create and activate a virtual environment:

    ```bash
    python -m venv env
    source env/bin/activate       # Mac/Linux
    ./env/Scripts/activate        # Windows
    ```

2. Install requirements:

    ```bash
    pip install -r requirements.txt
    ```

3. Create a `.env` file (or symlink to one) with credentials for the services you use:

    ```bash
    # Flask
    API_SECRET=your-secret-key

    # QuickBooks
    QB_CLIENT_ID=...
    QB_CLIENT_SECRET=...

    # Xero
    XERO_CLIENT_ID=...
    XERO_SECRET=...

    # Timely
    TIMELY_CLIENT_ID=...
    TIMELY_SECRET=...

    # Gusto
    GUSTO_CLIENT_ID=...
    GUSTO_SECRET=...
    GUSTO_COMPANY_ID=...

    # Airtable
    AIRTABLE_API_KEY=...
    AIRTABLE_TABLE=...

    # Cloze
    CLOZE_API_KEY=...

    # Google Sheets
    GSHEETS_SHEETNAME=...
    GSHEETS_SHEET_ID=...
    GSHEETS_WORKSHEET_NAME=...

    # AWS
    AWS_ACCESS_KEY_ID=...
    AWS_SECRET_ACCESS_KEY=...
    CLOUDFRONT_DISTRIBUTION_ID=...

    # KeyCDN
    KEYCDN_API_KEY=...

    # Mailgun
    MAILGUN_API_KEY=...
    MAILGUN_DOMAIN=...
    MAILGUN_SMTP_PASSWORD=...

    # Postmark
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

    The API is available at `http://localhost:5000/v1/`.

## Usage

### OAuth Authorization

Navigate to the auth endpoint for a provider to start the OAuth flow:

```
GET /v1/{provider}-auth
```

The callback is handled automatically at:

```
GET /v1/{provider}-callback
```

### Resource Endpoints

```
GET    /v1/{provider}-{resource}           # list or fetch resource
GET    /v1/{provider}-{resource}/{id}      # fetch by ID
POST   /v1/{provider}-{resource}           # create
PATCH  /v1/{provider}-{resource}/{id}      # update
DELETE /v1/{provider}-{resource}/{id}      # delete
```

Examples:

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

## Development

Install dev dependencies:

```bash
pip install -r dev-requirements.txt
```

Run tests:

```bash
python manage.py test
```

Lint:

```bash
python manage.py lint
```

## Configuration Reference

| Variable | Description |
|----------|-------------|
| `API_SECRET` | Flask app secret key |
| `QB_CLIENT_ID` / `QB_CLIENT_SECRET` | QuickBooks OAuth2 credentials |
| `XERO_CLIENT_ID` / `XERO_SECRET` | Xero OAuth credentials |
| `TIMELY_CLIENT_ID` / `TIMELY_SECRET` | Timely OAuth2 credentials |
| `GUSTO_CLIENT_ID` / `GUSTO_SECRET` | Gusto OAuth2 credentials |
| `GUSTO_COMPANY_ID` | Gusto company ID |
| `AIRTABLE_API_KEY` / `AIRTABLE_TABLE` | Airtable credentials |
| `CLOZE_API_KEY` | Cloze API key |
| `GSHEETS_SHEETNAME` / `GSHEETS_SHEET_ID` / `GSHEETS_WORKSHEET_NAME` | Google Sheets config |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS credentials |
| `CLOUDFRONT_DISTRIBUTION_ID` | AWS CloudFront distribution |
| `KEYCDN_API_KEY` | KeyCDN API key |
| `MAILGUN_API_KEY` / `MAILGUN_DOMAIN` / `MAILGUN_SMTP_PASSWORD` | Mailgun credentials |
| `POSTMARK_ACCOUNT_TOKEN` / `POSTMARK_SERVER_TOKEN` | Postmark credentials |
| `MAILGUN_LIST_PREFIX` | Prefix for Mailgun mailing lists |

## Production

The app detects production by the presence of a `DATABASE_URL`, `REDIS_URL`, `MEMCACHIER_SERVERS`, or `REDISTOGO_URL` environment variable. In production, [Talisman](https://github.com/GoogleCloudPlatform/flask-talisman) (HTTPS enforcement) and memcache are enabled automatically.

For staging, set:

```bash
heroku config:set STAGE=true --remote staging
```
