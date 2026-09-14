# prometheus-legacy

An archive of the legacy **Prometheus** project — a [Flask](http://flask.pocoo.org)
powered stock-portfolio and asset-allocation tool. Prometheus tells investors how their
portfolio has performed over time, helps optimize asset allocation, and flags
rebalancing or performance-enhancing opportunities, with a focus on building portfolios
of low-cost ETFs and mutual funds tailored to individual risk tolerance.

This repository collects the successive iterations of Prometheus (all legacy, Python 2
era) plus related design and reference material. It is kept for historical reference and
is not actively maintained.

## Contents

| Directory | Description |
| --------- | ----------- |
| `archive/` | The earliest iteration — the original full Prometheus web app |
| `apollo/` | A later Prometheus web app ("a global asset allocation tool"); includes a screenshot |
| `atlas/` | **Prometheus-API** — the Flask-Restless + SQLAlchemy RESTful API backend behind the web app |
| `compositions/` | Portfolio marketing / design compositions (images) |
| `screenshots/` | Application screenshots |
| `techstack.key/` | Keynote presentation of the tech stack |
| `vgstx.txt` | Reference data: Vanguard STAR Fund (VGSTX) holdings breakdown |

## Iterations

Each app subdirectory is a self-contained Flask project with its own `README.rst`,
`requirements.txt`, `manage.py`, and `Procfile` (Heroku-style):

- **archive** and **apollo** are the web-app front ends.
- **atlas** (Prometheus-API) is the REST API that serves portfolio data — database
  abstraction via SQLAlchemy, validation via SAValidation, and API generation via
  Flask-Restless.

See the individual `README.rst` files in `apollo/`, `atlas/`, and `archive/` for
per-project setup and usage details.

## Status

Legacy / archived. These projects target Python 2.7 (atlas also mentions early Python 3)
and pinned, now-outdated Flask-era dependencies. They are not expected to run as-is on
modern environments without updates.
