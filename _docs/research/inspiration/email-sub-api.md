---
source: ../../../../email-sub-api/README.md
---

# email-sub-api

**Nerevu Subscription API** — a [Mailgun][mailgun]-powered Flask API to subscribe
readers to email lists with a double opt-in, paired with a worker that watches an
RSS/Atom feed and emails the mailing list whenever a new post is published.

- **Version:** 0.11.0
- **License:** MIT
- **Author:** Reuben Cummings

[mailgun]: https://www.mailgun.com/

## Components

The app runs as two Heroku-style processes (see `Procfile`):

- **web** — the Flask subscription/logging API (served with gunicorn + gevent).
- **worker** — a feed monitor (`manage.py watch`) built on [chakula][chakula] that
  polls a [FeedBurner][fb] feed once an hour (`DEF_INTERVAL = 60 * 60`,
  `app/watch.py:26`) and emails the mailing list on new entries. As shipped the
  worker stops with a `RuntimeError` before polling unless `SERVER_NAME` is set (see
  [Known issues](#known-issues)).

The worker sends its high-level logs to the API's `/log` route through a webhook
handler (`app/watch.py:65-77`); that route is broken, so those alerts are lost.

[chakula]: https://github.com/reubano/chakula
[fb]: https://feedburner.google.com/

## API endpoints

All routes are also available under the `/v1` prefix (`API_URL_PREFIX`).

| Method(s) | Route | Description |
| --------- | ----- | ----------- |
| `GET` | `/`, `/v1` | Welcome message (HTML) |
| `POST` | `/subscription`, `/v1/subscription` | Validates the email address and sends a confirmation email. Does not subscribe anyone. |
| `GET` | `/subscription`, `/v1/subscription` | The confirmation link: checks `hash` and then subscribes the address to the list. Optionally sends a "swag" email. |
| `GET` `POST` | `/log`, `/v1/log` | Meant as a log sink that emails the admin; raises `AttributeError` (HTTP 500) on every request as shipped. |

### Subscription flow (double opt-in)

1. `POST /subscription` with form fields (`app/__init__.py:54-88`):
   - `honey` non-empty → `403` "You appear to be a bot." (honeypot field);
   - no `email` → `400` "You must provide an email address.";
   - otherwise the address is checked with Mailgun's address validation API. An
     invalid address → `400`, with `suggestion` set to Mailgun's `did_you_mean` and
     the message "Perhaps you meant ...?" when there is one;
   - a valid address → a confirmation email is sent and the response is `200`
     "`<list>` list subscription confirmation sent to `<email>`."; if the send
     fails the response is `400` with Mailgun's error (`app/__init__.py:73-79`).
2. The confirmation email links to `GET /subscription` with `hash`, `email`,
   `domain`, `list` and `format=html` (`app/mailgun.py:190-192`). `hash` is the MD5
   of `<email>:<list>:<SECRET>` (`app/mailgun.py:52-55`).
3. `GET /subscription` (`app/__init__.py:91-113`) recomputes the hash from the
   query's `email` and `list`; a mismatch → `401` "Failed to verify ...". A match adds
   the address as a subscribed member of the Mailgun list `<list>@<domain>` and
   returns `200` "Thanks for subscribing ...". `domain` and `list` come from the
   query string, so the link decides which list is joined.
4. If the `GET` succeeded and has a `swag` parameter, a second email with the
   requested document is sent. The only document is `guide` ("You Might Not Need
   Pandas"); any other value returns `404` "SWAG item '...' doesn't exist."
   The confirmation link does not carry `swag` (see [Known issues](#known-issues)),
   so this happens only when `swag` is added to the link by hand.

Request parameters (form fields for `POST`, query arguments for `GET`):

| Parameter | Meaning | Default |
| --------- | ------- | ------- |
| `email` | Subscriber address | required |
| `list` | Mailing list name | `blog` (`DEF_MLIST`) |
| `domain` | Mailing list / sending domain | `notify.nerevu.com` (`DEF_LIST_DOMAIN`) |
| `hash` | Confirmation hash (`GET`) | none |
| `honey` | Honeypot; any value rejects the request (`POST`) | none |
| `swag` | Document to send after confirming (`GET`) | none |
| `mock` | Any non-empty value skips the Mailgun validation, subscribe and send calls and uses canned results (`app/mailgun.py:41-49,66-68,151-152,168-169`); only the addresses in the canned table (`email`, `fake@email.com`) avoid a `KeyError` | off |
| `format` | Query argument only, on both methods: `json`, or anything else for an HTML page (`<h1>Success!</h1>` / `<h1>Error.</h1>` plus the message) | `json` |

The request can also override the other defaults the route passes to `Mailgun`
(`debug`, `postal_address`, `admin_name`, `company_name`), because all request
values are merged over them (`app/__init__.py:165-175`).

JSON responses carry the outcome in the HTTP status code; the body holds `message`
(and `suggestion` for `POST`). Every request to `/subscription` makes a Mailgun API
call to look up the list's display name (`app/mailgun.py:105`, `config.py:63-66`).

## Requirements

- Python 3.6 (`runtime.txt` pins 3.6.6)
- A [Mailgun](https://www.mailgun.com/) account (private API key and public
  validation key)
- Redis (optional — used by the worker's feed cache with `-r`)

```bash
pip install -r requirements.txt      # or base-requirements.txt for the minimal set
pip install -r dev-requirements.txt  # development/testing
```

## Configuration

Configuration is selected by mode (`Development`, `Production`, `Heroku`, `Custom`,
`Test`) in `config.py`. Secrets and environment-specific values come from
environment variables:

| Variable | Purpose |
| -------- | ------- |
| `MAILGUN_API_KEY` | Mailgun private API key for sending, subscribing and list lookups (**required**) |
| `MAILGUN_API_PUBKEY` | Mailgun public key for address validation (`app/mailgun.py:23,72`) |
| `SECRET` | Salt for the confirmation hash. Defaults to `'$eCr3t'` (`app/mailgun.py:24`); set it, or anyone can build valid confirmation links |
| `REDISTOGO_URL` | Redis URL for `watch -r` (default `redis://localhost:6379`, `app/connection.py:12`) |
| `DATABASE_URL` | Marks a production server: sets `SERVER_NAME` in `Heroku`/`Custom`, which also turns on SSLify (`app/__init__.py:149-150`). No database is used. |
| `STAGE` | Set on a staging server; adds `-stage` to the server name |
| `MAILGUN_DOMAIN` | Sets `Config.MG_DOMAIN`/`MG_URL`, which nothing in `app/` reads |
| `MAILGUN_SANDBOX` | Fallback for `MG_DOMAIN` when `MAILGUN_DOMAIN` is unset; likewise unread |

Mail is sent through `https://api.mailgun.net/v3/<domain>/messages`, where `<domain>`
is the request's `domain` or `DEF_LIST_DOMAIN` (`app/mailgun.py:161`), not
`MAILGUN_DOMAIN`. Emails come from `<ADMIN name> <owner@<domain>>`.

Defaults in `config.py`: mailing list `blog`, list domain `notify.nerevu.com`,
FeedBurner list `reubano` (`DEF_FB_LIST`, which `watch` never falls back to; see
[`watch` options](#run-the-feed-watcher)), company `Nerevu Gropup, LLC`
(spelled that way in `config.py:38`; it appears in every email footer) and postal
address `820 SW Adams St. Peoria, IL 61602`.

Importing `config.py` runs `check_domain('subscription.com')`, an HTTP request to
Mailgun's domains API, in every mode (`config.py:131-137`). With an active domain the
unused `MG_DOMAIN` is replaced.

Server names: `Heroku` uses `subscription-api[-stage].herokuapp.com`, `Custom` uses
`api[-stage].subscription.com`, both only when `DATABASE_URL` is set.

## Usage

### Run the API (development)

```bash
./manage.py runserver                    # Flask-Script built-in; defaults to port 5000
./manage.py -m Development runserver     # explicitly select a config mode
```

### Run the feed watcher

```bash
# Watch the reubano FeedBurner list, showing entries newer than a date
./manage.py watch -F reubano -v -a '1/1/17'

# Watch a specific feed URL, using redis for the cache
./manage.py watch -f https://feeds.feedburner.com/reubano -r -v
```

Both examples stop with a `RuntimeError` in the default `Development` mode, which
has no `SERVER_NAME` (see [Known issues](#known-issues)).

`watch` options:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `-f, --feed` | Feed URL | `https://feeds.feedburner.com/<fb-list>` |
| `-F, --fb-list` | FeedBurner list name | none: without `-f` or `-F` the feed is `https://feeds.feedburner.com/None` |
| `-c, --cache` | Cache file path | none |
| `-r, --redis` | Use Redis (`REDISTOGO_URL`) for the cache (takes precedence over `-c`) | off |
| `-l, --log-file` | File opened in append mode and passed to chakula as its output stream | none |
| `-a, --after` | Only process entries updated after this date (passed to chakula as `newer`) | none |
| `-p, --port` | Port put into the `/log` URL when that URL points at `localhost` | 5000 |
| `-v, --verbose` | Debug logging | off |

How new entries are found: chakula tails the feed every hour in reverse order. With
`-c` or `-r`, the stored state is loaded at start and updated after each poll
(`app/watch.py:99-121`); with neither, no cache is loaded or saved
(`app/watch.py:106-107`).

What is sent for each new entry (`app/watch.py:34-57`, `app/mailgun.py:249-265`):
an email to the list address `blog@notify.nerevu.com` (the `DEF_MLIST` list at
`DEF_LIST_DOMAIN`) with the subject `[nerevu-blog] <entry title>`, the entry's link,
title and description in the body, an unsubscribe link, and the tags `update` and
`blog`. `send_post` supports only the lists `blog`, `gallery` and `portfolio`
(`SITE_ENTITIES`, `app/mailgun.py:36`); any other list raises `KeyError`.

### Production (Heroku)

```text
web:    gunicorn "app:create_app('Production')" -w 3 -k gevent
worker: python manage.py -m Production watch -vra '1/1/17'
```

The `Production` mode never sets `SERVER_NAME`, so this worker line stops with a
`RuntimeError`. The line also passes neither `-f` nor `-F`, so even with a server
name it would watch `https://feeds.feedburner.com/None`.

## Development

```bash
./manage.py test          # python -m pytest tests (see options below)
./manage.py lint          # flake8 (+ pylint with --strict)
./manage.py check         # lint staged changes (helpers/check-stage)
./manage.py clean         # remove build artifacts (helpers/clean)
./manage.py deploy        # heroku keys:add, then git push origin master
./manage.py require       # write requirements.txt from pip freeze
./manage.py noop          # exit 0 (for tox)
```

`test` options: `-x` stop after the first failure, `-f` rerun failed tests
(`--last-failed`), `-t` run tox, `-d` run detox. The remaining options pass nose flags
that pytest does not accept (observed with pytest 9.2): `-c` (`--with-coverage`), `-p`
(`--processes=-1`), `-v` (`--detailed-errors`) and `-w` (`-w <path>`) make pytest exit
with a usage error, and `-D` passes `--debug=nose.loader`, which pytest reads as the
name of a debug log file.

`pipme` is meant to install `requirements.txt` but fails (see
[Known issues](#known-issues)).

## Known issues

- `watch` raises `RuntimeError` ("Application was not able to create a URL adapter
  for request independent URL generation") from `url_for('log', _external=True)`
  unless `SERVER_NAME` is set (`app/watch.py:65`). Only `Heroku` and `Custom` set it,
  and only when `DATABASE_URL` is set (`config.py:147-148,158-159`). Observed with
  Flask 0.12.5, inside the `Flask>=0.12,<1.0.0` pin.
- Without `-f` or `-F`, the feed URL is `https://feeds.feedburner.com/None`:
  `-F` defaults to `None`, so `kwargs.get('fb_list', DEF_FB_LIST)` never falls back
  (`manage.py:107,127-128`). The `Procfile` worker passes neither.
- `/log` raises `AttributeError` on every request: `kwargs.iteritems()` does not
  exist on Python 3 (`app/__init__.py:214`). Past that line, `keys = {'blah',
  'blah'}` is a placeholder (`app/__init__.py:213`) and `mailgun.sub_domain` is never
  defined on `Mailgun` (`app/__init__.py:231`). The worker's error alerts posted
  there are lost.
- The confirmation link never includes `swag`: `&swag={swag}` is appended to the URL
  template after the URL has been built (`app/mailgun.py:192-195`).
- `mock` with an address other than `email` or `fake@email.com` (or, on `GET`, an
  `(email, list)` pair other than `('email', 'blog')` and `('fake@email.com',
  'beta')`) raises `KeyError` (`app/mailgun.py:41-49,68,169`).
- `SECRET` defaults to the published value `'$eCr3t'` (`app/mailgun.py:24`).
- Importing `config.py` makes a Mailgun HTTP request in every mode
  (`config.py:131-137`); `MG_AUTH` is always a non-empty tuple, so the `MOCK_R`
  fallback for a missing key (`config.py:48-50,58,65`) is never used.
- `./manage.py test` with `-c`, `-p`, `-v` or `-w` passes nose-only flags to pytest,
  which rejects them (`manage.py:88-93,101`).
- `./manage.py pipme` calls `subprocess.call('pip', 'install', '-r',
  'requirements.txt')` with separate arguments instead of a list, so `'install'`
  lands in `bufsize` and the call raises `TypeError: bufsize must be an integer`
  (observed on Python 3.11) (`manage.py:144`).

## License

MIT — see [LICENSE](LICENSE).
