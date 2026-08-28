# api-utils

A small collection of utility functions for building JSON [Flask](https://flask.palletsprojects.com/) APIs backed by [SQLAlchemy](https://www.sqlalchemy.org/). It bundles together the boilerplate that Nerevu's APIs share: response formatting, HTTP caching headers, HATEOAS-style link generation, and SQLAlchemy model/table introspection.

## Requirements

- Python 3.7+
- [Flask](https://flask.palletsprojects.com/)
- [SQLAlchemy](https://www.sqlalchemy.org/) >= 1.2, < 3.0
- [meza](https://github.com/reubano/meza) >= 0.45.5
- [python-dateutil](https://dateutil.readthedocs.io/) >= 2.8.2

## Installation

```sh
pip install nerevu-api-utils
```

Or from source:

```sh
git clone https://github.com/reubano/api-utils.git
cd api-utils
pip install -r requirements.txt
```

## Usage

The library is a single module, `api_utils`.

```python
import api_utils as au
```

### JSON responses

`jsonify` (a partial of `responsify`) builds a Flask response that correctly serializes sets, dates, and iterators — cases the stock `flask.jsonify` doesn't handle.

```python
from api_utils import jsonify

@app.route("/v1/data")
def data():
    return jsonify(result=[{"id": 1, "name": "Alice"}], status_code=200)
```

### Caching headers

`cache_header` decorates a view to set `Cache-Control`, `ETag`, and `Expires` headers based on a `max_age` (in seconds). Set `max_age=0` to disable caching.

```python
from api_utils import cache_header

@app.route("/map")
@cache_header(cache, 60)
def index():
    return render_template("index.html")
```

Related helpers: `make_cache_key`, `delete_cache`, `uncache_header`, and `get_mimetype`.

### API links (HATEOAS)

`get_links` turns a set of URL rules into a sorted list of `{"rel", "href", "method"}` link objects, useful for exposing a discoverable API index.

```python
from api_utils import get_links

links = get_links(app.url_map.iter_rules())
# [{"rel": "data", "href": "https://.../v1/data", "method": "GET"}, ...]
```

### SQLAlchemy introspection

Generators for classifying and ordering mapped tables — handy for seeding, migrations, and dependency-aware iteration:

- `gen_models` / `gen_tables` — discover models and their mapped tables
- `get_table`, `get_col_type`
- `gen_independent_tables`, `gen_dependent_tables`, `gen_association_tables`
- `get_all_tables` — returns independent, dependent, association, and combined table lists
- `add_listener`, `trim_entry` — attach column event listeners (e.g. strip whitespace)
- `SQLALCHEMY_NAMING_CONVENTION`, `auto_constraint_name` — consistent constraint naming for Alembic

### Miscellaneous helpers

- `parse` — parse a string into its equivalent Python object
- `configure` — load Flask config from a file, env var, or config object
- `parse_kwargs` — parse and whitelist request query args
- `get_seconds`, `fmt_elapsed` — time helpers
- `title_case`, `strip_slash`, `singularize`, `get_hash`

## Development

Install dev dependencies and run the tasks via [`manage.py`](manage.py):

```sh
pip install -r dev-requirements.txt

python manage.py test        # run tests (doctests + nose)
python manage.py lint        # flake8 / pylint
python manage.py prettify    # format with black
python manage.py build       # build sdist + wheel
```

## License

[MIT](LICENSE) © Reuben Cummings
