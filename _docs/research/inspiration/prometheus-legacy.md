---
source: ../../../../prometheus-legacy/README.md
---

# prometheus-legacy

An archive of the legacy **Prometheus** project — a [Flask](http://flask.pocoo.org)
powered stock-portfolio and asset-allocation tool. Prometheus tells investors how their
portfolio has performed over time, helps optimize asset allocation, and flags
rebalancing or performance-enhancing opportunities, with a focus on building portfolios
of low-cost ETFs and mutual funds tailored to individual risk tolerance.

This directory collects the successive iterations of Prometheus (all legacy, Python 2 /
early Python 3 era) plus related design and reference material. It is not itself a git
repository: `archive/`, `apollo/`, and `atlas/` are three independent git repositories,
and the remaining files are loose assets. It is kept for historical reference and is not
actively maintained.

The iterations trace a move from one monolithic app to a split between a UI and an API:
`archive` bundles the UI, the data models, and the REST API in one app; `apollo` is a
UI-only client; and `atlas` holds the models and the REST API that `apollo` calls.

## Contents

| Directory | Description |
| --------- | ----------- |
| `archive/` | The earliest iteration — the original full Prometheus web app: a monolith with its own UI, SQLAlchemy models, Flask-Restless REST API, and rq background worker |
| `apollo/` | A later Prometheus web app ("a global asset allocation tool"), UI only: it has no models and reads and writes its data through the `atlas` API over HTTP; includes a screenshot |
| `atlas/` | **Prometheus-API** — the Flask-Restless + SQLAlchemy RESTful API and data layer behind `apollo` |
| `compositions/` | Portfolio marketing / design compositions (images) |
| `screenshots/` | Application screenshots, grouped by device (`air/`, `imac/`, `iphone/`, `macbook/`, `mini/`) |
| `techstack.key/` | Keynote presentation of the tech stack |
| `vgstx.txt` | Reference data: Vanguard STAR Fund (VGSTX) holdings breakdown, as of October 31, 2014 |

## Iterations

Each app subdirectory is a self-contained Flask project with its own `README.rst`,
`requirements.txt`, `manage.py`, and `Procfile` (Heroku-style). In `apollo/`,
`requirements.txt` does not install as shipped (see [Known issues](#known-issues)); its
installable requirement files are `prod.txt` (which includes `common.txt`), `dev.txt`,
and `test.txt` at the top of `apollo/`.

- **archive** is the original monolith. It keeps its own SQLAlchemy models in
  `app/apollo/models.py`, `app/cronus/models.py`, and `app/hermes/models.py`, generates
  a Flask-Restless endpoint for each model at `/api/<tablename>` (`app/__init__.py`),
  and runs an [rq](https://python-rq.org) worker on Redis next to the web process
  (`Procfile`: `worker: python worker.py`).
- **apollo** is the web-app front end. It has no database models of its own: every read
  and write goes over HTTP to the atlas API (`app/connection.py`). The API base URL is
  hardcoded as `__API_BASE__ = 'http://prometheus-api.herokuapp.com/'` in `config.py`,
  with a commented-out `http://localhost:5005/` alternative for local development.
- **atlas** (Prometheus-API) is the REST API that serves portfolio data — database
  abstraction via SQLAlchemy, validation via SAValidation, and API generation via
  Flask-Restless. Its models fall into two groups (`app/models/`): portfolio models
  (`icarus`: Person, Company, AccountType, TrxnType, Account, Contribution, Holding,
  Transaction) and market/commodity models (`hermes`: Exchange, DataSource,
  CommodityGroup, CommodityType, Commodity, EventType, Event, Price). Each model gets an
  auto-generated REST endpoint; the "Resources" section of `atlas/README.rst` lists them
  with atlas's custom endpoints.

See the individual `README.rst` files in `apollo/`, `atlas/`, and `archive/` for
per-project setup and usage details.

The `apollo` and `atlas` working trees differ from their last commits, and this readme
describes the working trees.

## Status

Legacy / archived. These projects target pinned, now-outdated Flask-era dependencies and
are not expected to run as-is on modern environments without updates. Their Python
targets differ:

| App | Heroku `runtime.txt` | Its `README.rst` says |
| --- | -------------------- | --------------------- |
| `archive/` | `python-2.7.1` | Python 2.7.1 |
| `apollo/` | `python-3.6.1` (the last commit has `python-2.7.1`) | Python 2.7.4 |
| `atlas/` | `python-3.6.0` | Python 2.7, 3.5, and 3.6 (plus a `py2-requirements.txt`) |

## Known issues

- `apollo/requirements.txt` contains only `-r requirements/prod.txt`, but the
  `apollo/requirements/` directory no longer exists in the working tree (its files moved
  to the top of `apollo/`), so `pip install -r requirements.txt` fails. Use
  `pip install -r prod.txt` from `apollo/` instead.
- `apollo/README.rst` installs with `pip install -r requirements-local.txt`, a file that
  does not exist.
- `apollo` needs a running atlas API at the hardcoded `__API_BASE__` in
  `apollo/config.py`; there is no environment variable to point it elsewhere, so a local
  setup means editing that line.
