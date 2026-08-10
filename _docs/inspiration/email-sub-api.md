# email-sub-api

**Nerevu Subscription API** — a [Mailgun][mailgun]-powered Flask API to subscribe
readers to email lists, paired with a worker that watches an RSS/Atom feed and emails
the mailing list whenever a new post is published.

- **Version:** 0.11.0
- **License:** MIT
- **Author:** Reuben Cummings

[mailgun]: https://www.mailgun.com/

## Components

The app runs as two Heroku-style processes (see `Procfile`):

- **web** — the Flask subscription/logging API (served with gunicorn + gevent).
- **worker** — a feed monitor (`manage.py watch`) built on [chakula][chakula] that
  polls a [FeedBurner][fb] feed and emails the mailing list on new entries.

[chakula]: https://github.com/reubano/chakula
[fb]: https://feedburner.google.com/

## API endpoints

All routes are also available under the `/v1` prefix (`API_URL_PREFIX`).

| Method(s) | Route | Description |
| --------- | ----- | ----------- |
| `GET` | `/`, `/v1` | Welcome message |
| `GET` `POST` | `/subscription`, `/v1/subscription` | Look up (`GET`) or create (`POST`) a subscriber on the Mailgun mailing list. Optionally sends a "swag" welcome email. Returns JSON (or HTML with `?format=html`). |
| `GET` `POST` | `/log`, `/v1/log` | Webhook log sink — emails the admin with the posted log data. |

## Requirements

- Python 3
- A [Mailgun](https://www.mailgun.com/) account (API key + domain)
- Redis (optional — used by the worker's feed cache)

```bash
pip install -r requirements.txt      # or base-requirements.txt for the minimal set
pip install -r dev-requirements.txt  # development/testing
```

## Configuration

Configuration is selected by mode (`Development`, `Production`, …) in `config.py`.
Secrets and environment-specific values come from environment variables:

| Variable | Purpose |
| -------- | ------- |
| `MAILGUN_API_KEY` | Mailgun API key (**required**) |
| `MAILGUN_DOMAIN` | Sending domain |
| `MAILGUN_SANDBOX` | Sandbox subdomain (used if no domain is set) |
| `DATABASE_URL` | Production database / server URL |
| `STAGE` | Staging server URL |

Defaults (mailing list `blog`, list domain `notify.nerevu.com`, FeedBurner list
`reubano`, company/postal address) are defined in `config.py`.

## Usage

### Run the API (development)

```bash
./manage.py runserver                    # Flask-Script built-in; defaults to port 5000
./manage.py -m Development runserver     # explicitly select a config mode
```

### Run the feed watcher

```bash
# Watch the default FeedBurner list, showing entries newer than a date
./manage.py watch -v -a '1/1/17'

# Watch a specific feed URL, using redis for the cache
./manage.py watch -f https://feeds.feedburner.com/reubano -r -v
```

`watch` options:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `-f, --feed` | Feed URL | built from `DEF_FB_LIST` |
| `-F, --fb-list` | FeedBurner list name | `reubano` |
| `-c, --cache` | Cache file path | none |
| `-r, --redis` | Use Redis for the cache (takes precedence over `-c`) | off |
| `-l, --log-file` | Log file path | none |
| `-a, --after` | Only process entries updated after this date | none |
| `-p, --port` | Server port (for the log webhook URL) | 5000 |
| `-v, --verbose` | Debug logging | off |

### Production (Heroku)

```
web:    gunicorn "app:create_app('Production')" -w 3 -k gevent
worker: python manage.py -m Production watch -vra '1/1/17'
```

## Development

```bash
./manage.py test          # run pytest (options: -x, -c coverage, -t tox, -p parallel)
./manage.py lint          # flake8 (+ pylint with --strict)
./manage.py check         # lint staged changes
./manage.py clean         # remove build artifacts
```

## License

MIT — see [LICENSE](LICENSE).
