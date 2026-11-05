---
source: ../../../../api-utils/README.md
---

# api-utils

A small collection of utility functions for building JSON
[Flask](https://flask.palletsprojects.com/) APIs backed by
[SQLAlchemy](https://www.sqlalchemy.org/). It bundles together the boilerplate that
Nerevu's APIs share: response formatting, HTTP caching headers, HATEOAS-style link
generation, and SQLAlchemy model/table introspection.

## Requirements

- Python 3.8+ (the caching code uses assignment expressions)
- [Flask](https://flask.palletsprojects.com/)
- [SQLAlchemy](https://www.sqlalchemy.org/) >= 1.2, < 3.0
- [meza](https://github.com/reubano/meza) >= 0.45.5
- [python-dateutil](https://dateutil.readthedocs.io/) >= 2.8.2
- [inflect](https://pypi.org/project/inflect/) (used by `singularize`, `get_table`, and
  `gen_dependent_tables`)
- A [Flask-Caching](https://flask-caching.readthedocs.io/) `Cache` object for the
  caching helpers (you create it and pass it in)

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

`api_utils` imports `inflect` at module load, but neither `requirements.txt` nor the
package's install requirements list it, so install it yourself:

```sh
pip install inflect
```

## Usage

The library is a single module, `api_utils`.

```python
import api_utils as au
```

### JSON responses

`jsonify` (a partial of `responsify` with the `application/json` mimetype) builds a
Flask response that correctly serializes sets, dates, and iterators — cases the stock
`flask.jsonify` doesn't handle.

```python
from api_utils import jsonify


@app.route("/v1/data")
def data():
    return jsonify(result=[{"id": 1, "name": "Alice"}], status_code=200)
```

`GET /v1/data` returns:

```json
{
  "result": [
    {
      "id": 1,
      "name": "Alice"
    }
  ],
  "status": "OK"
}
```

`responsify(mimetype, status_code=200, indent=2, sort_keys=True, **kwargs)` works as
follows:

- Every keyword argument becomes a top-level key of the body.
- The body always gets a `"status"` key holding the HTTP reason phrase for `status_code`
  (`"OK"`, `"Not Found"`, …).
- JSON bodies are encoded with meza's `CustomEncoder` (sets, dates, iterators),
  `indent=2`, `ensure_ascii=False`, and **sorted keys**, so the same data always
  serializes to the same bytes.
- A mimetype ending in `csv` renders the `result` list of records as CSV (e.g.
  `a,b\r\n1,2\r\n`). Any other non-JSON mimetype, or `csv` without a `result`, gives an
  empty body.
- `Content-Type` is `<mimetype>; charset=<encoding>`. `encoding` defaults to `utf-8`. An
  `encoding=` keyword sets the charset and also appears in the JSON body as an
  `"encoding"` key.
- Every response gets `Last-Modified` set to the current time and an `ETag` computed
  from the body.

### Caching headers

`cache_header(cache, max_age, versioned=False, refresh_period=None, **ckwargs)`
decorates a view to set `Cache-Control`, `ETag`, and `Expires` headers based on a
`max_age` (in seconds). Set `max_age=0` to disable caching. It also caches the view's
response on the server: the view is wrapped in `cache.cached(max_age, **ckwargs)`, so
`cache` must be a Flask-Caching `Cache` and any extra keyword arguments (e.g.
`key_prefix=make_cache_key`) go to `cache.cached`.

```python
from api_utils import cache_header


@app.route("/map")
@cache_header(cache, 60)
def index():
    return render_template("index.html")
```

The headers are derived as follows:

| Case | Headers |
| ---- | ------- |
| `max_age > 0`, `GET` request | `max-age=<max_age>`, `s-maxage=<max_age // 2>`, `must-revalidate`, `public`, an `ETag`, and `stale-while-revalidate`/`stale-if-error` set to `refresh_period` |
| `versioned=True` (and `max_age > 0`) | `max_age` is replaced by one year (31536000 s), and `immutable` replaces `must-revalidate` |
| `refresh_period` | defaults to one day (86400 s); `0` omits the `stale-*` directives |
| `Expires` | `Last-Modified + max_age`. Without `Last-Modified`, a numeric `utc_requested` timestamp in the JSON body is used instead. When there is neither, no `Expires` is set. `jsonify` responses always have `Last-Modified`, so for them `Expires` is now + `max_age`. |
| `max_age=0`, or any non-`GET` request | `no-store`, `max-age=0`, `Pragma: no-cache`, not `public`, and `Expires` = `Last-Modified` (or now) |

Every response then goes through `make_conditional`, so a request whose `If-None-Match`
matches the `ETag` gets a `304 Not Modified`.

A `jsonify` view decorated with `@cache_header(cache, 60)` returns:

```text
Cache-Control: max-age=60, s-maxage=30, must-revalidate, public, stale-while-revalidate=86400, stale-if-error=86400
Expires: <Last-Modified + 60 s>
ETag: "<sha1 of the body>"
```

and with `versioned=True`:

```text
Cache-Control: max-age=31536000, s-maxage=15768000, immutable, public, stale-while-revalidate=86400, stale-if-error=86400
```

`max_age=0` only disables the caching *headers*: the server-side `cache.cached(0)` still
stores the first response with no expiry (see [Known issues](#known-issues)).

Related helpers:

- `make_cache_key(*args, cache_query=False, cache_mimetype=False, path=None, **kwargs)`
  builds a key from the request path (or `path`) with the trailing slash removed, e.g.
  `/v1/data`. `cache_query=True` appends `:<md5 of the query string>`;
  `cache_mimetype=True` appends `:<get_mimetype(request)>`.
- `delete_cache(cache, cache_key=None, clear=False, **kwargs)` returns a message. With
  `cache_key`, or inside a request with `clear=False`, it deletes one key
  (`make_cache_key(**kwargs)` when no key is given) and returns
  `"Deleted cache for <key>!"`. A two-part key such as `/v1/data:<hash>` clears the
  **whole** cache instead, since every downstream key (e.g. every page of a paginated
  route) is stale too. Outside a request, or with `clear=True`, it clears the whole
  cache and returns `"All caches cleared!"`.
- `uncache_header(cache, response)` calls `delete_cache(cache)` (the current path's
  entry inside a request, everything outside one) and applies the `max_age=0` headers to
  `response` in place. It returns `None`.
- `get_mimetype(request)` returns the best match from `MIMETYPES` for the request's
  `Accept` header when it is preferred over `text/html`, else `text/html`.

### API links (HATEOAS)

`get_links` turns a set of URL rules into a sorted list of `{"rel", "href", "method"}`
link objects, useful for exposing a discoverable API index. It reads the current
request, so call it inside a view.

```python
from api_utils import get_links, jsonify


@app.route("/v1/data/<int:id>", methods=["GET", "DELETE"])
def item(id):
    return jsonify(links=get_links(app.url_map.iter_rules()))
```

With `/v1/data` and `/v1/data/<int:id>` registered, the links are:

```json
[
  {"href": "http://localhost/v1/data", "method": "GET", "rel": "data"},
  {"href": "http://localhost/v1/data/<int:id>", "method": "GET", "rel": "data_id"},
  {"href": "http://localhost/v1/data/<int:id>", "method": "DELETE", "rel": "data_delete_id"}
]
```

The links are built as follows:

- Rules containing `static` or `callback`, and the root rule `/`, are skipped. `HEAD`
  and `OPTIONS` are skipped.
- `href` is the request's URL root plus the rule, with any trailing slash removed. Rule
  placeholders such as `<int:id>` are kept as-is.
- `rel` is `self` when `href` and method match the current request.
- Otherwise the resource name is the second path segment (the first if there is only
  one), e.g. `data` for `/v1/data`. A `(resource, method)` pair listed in
  `COMMON_ROUTES` or `AUTH_ROUTES` uses that table's rel: `v1` GET → `home`, `ipsum` GET
  → `ipsum`, `memoization` GET/DELETE → `memoize`/`reset`, `auth` GET/DELETE →
  `authenticate`/`revoke`, `refresh` GET → `refresh`, `status` GET → `status`. Any other
  pair uses the resource name, plus `_<method>` for non-`GET` methods.
- The rule's parameter names are appended, joined by `_` (`data_delete_id`).
- Links are sorted by `href`.

The building blocks are also exported: `gen_links(rules)` (the unsorted generator),
`get_rel(href, method, rule)`, `get_resource_name(rule)`, `get_params(rule)` (e.g.
`['path', 'status_type']` for `/v1/random_resource/<string:path>/<status_type>`),
`get_url_root()`, and `get_request_base()` (the last segment of the request's base URL).

### SQLAlchemy introspection

Generators for classifying and ordering mapped tables — handy for seeding, migrations,
and dependency-aware iteration:

- `gen_models` / `gen_tables` — discover models and their mapped tables.
  `gen_models(model_file="models", model_dir=None)` imports `app.<model_file>`, or each
  non-underscore `.py` file in `model_dir` as `app.models.<name>`, so it assumes an
  `app` package. `gen_tables(models)` yields every class in those modules with a
  `__tablename__`.
- `get_table(tables, tablename, singularize=False)` (returns `None` when not found),
  `get_col_type(col, table)`
- `gen_independent_tables`, `gen_dependent_tables`, `gen_association_tables` — the
  dependency rules:
  - a column ending in `_id` is a dependency on the table named by its prefix (`user_id`
    → `user`), and a backref relationship that isn't already a column counts as one too
    (singularized);
  - an **independent** table has no dependencies;
  - an **association** table has exactly two `_id` columns;
  - `gen_dependent_tables(tables, dependency, seen=None)` yields, depth first, each
    table that depends on `dependency` once all of its dependencies are in `seen`, so a
    table always comes after the tables it references.
- `get_all_tables` — returns independent, dependent, association, and combined table
  lists, as a dict with the keys `independent_tables`, `dependent_tables`,
  `association_tables`, `non_association_tables`, and `all_tables` (independent then
  dependent, in dependency order).
- `gen_cols`, `gen_independent_cols`, `gen_dependent_cols`, `gen_relationships` — the
  column/relationship generators the rules above use. Each takes `excluded_cols`. They
  read the column list from the model's `_sav_column_names()` method, so the models must
  provide it.
- `add_listener`, `trim_entry` — attach column event listeners (e.g. strip whitespace).
  `add_listener(listener, *tables, field="name", etype="set")` skips tables without
  `field`. `trim_entry` strips the value and stores `None` for an empty one.
- `SQLALCHEMY_NAMING_CONVENTION`, `auto_constraint_name` — consistent constraint naming
  for Alembic (unnamed constraints get `sa_autoname_<5 random hex chars>`)
- `CASCADE` (`"save-update, merge, refresh-expire, expunge"`) and `FK_KWARGS`
  (`onupdate="CASCADE"`, `ondelete="SET NULL"`) — relationship/foreign-key defaults

### Miscellaneous helpers

- `parse` — parse a string into its equivalent Python object (`'True'` → `True`,
  `'{"key": "value"}'` → a dict; anything that isn't a literal comes back unchanged)
- `configure(flask_config, config, **kwargs)` — load Flask config from a file
  (`config_file`), env var (`config_envvar`), or config object (`config_mode`, an
  attribute of `config`), checked in that order; with none, it loads the file named by
  `APP_SETTINGS` if that is set
- `parse_kwargs(app, whitelist=None)` — parse the request query args with `parse`, then
  add each whitelisted app config key (lowercased) the query didn't set
- `get_seconds(seconds=0, months=0, years=0, **timedelta_kwargs)` (months are 30 days,
  years 365), `fmt_elapsed` (yields e.g. `'16 minutes'`, `'40 seconds'`) — time helpers
- `fetch_bool(message, voice_over=False)` — prompt on the terminal until the answer is
  `y` or `n` (empty means `n`); `voice_over` also speaks a prompt with macOS `say`
- `title_case`, `strip_slash` (removes the trailing slash; keyword arguments are
  appended as a query string), `singularize`, `get_hash` (md5 hex digest)
- Constants: `MIMETYPES`, `ENCODING` (`utf-8`), `EPOCH`, `HEADERS`
  (`{"Accept": "application/json"}`), `TODAY`, `YESTERDAY` (fixed at import time),
  `COMMON_ROUTES`, `AUTH_ROUTES`

## Development

Install dev dependencies and run the tasks via [`manage.py`](manage.py):

```sh
pip install -r dev-requirements.txt

python manage.py test        # run tests (doctests + nose)
python manage.py lint        # flake8 (add -s for pylint)
python manage.py prettify    # format with black
python manage.py build       # build sdist + wheel
```

`test` runs `nosetests`. There is no test suite beyond the module doctests, which
nose collects because `setup.cfg` enables its doctest plugin. Its options are `-w`
(test path), `-x` (stop on first error), `-f` (rerun failed), `-c` (coverage), `-t`
(`tox`; there is no `tox.ini`), `-d` (`detox`), `-v`, `-p` (parallel), and `-D`
(loader debugging). Both nose and the doctests fail on current Python (see
[Known issues](#known-issues)).

Other commands: `check` (lint staged changes), `pipme` (install `requirements.txt`),
`require` (regenerate `requirements.txt` from `pip freeze`), `release` (clean,
build, and upload to PyPI), `upload`, `sdist`, `wheel`, `clean`, and `docs`.

## Known issues

- `import api_utils` fails with `ModuleNotFoundError: No module named 'inflect'` unless
  `inflect` is installed separately. It is imported at `api_utils.py:33` but missing
  from `requirements.txt`.
- `setup.py` still lists Python 3.7 among its classifiers, but `api_utils.py:180` and
  `:183` use assignment expressions (3.8+).
- `cache_header(cache, 0)` still caches the view on the server: `cache.cached(0)`
  (`api_utils.py:162`) stores the first response with no expiry, so every later request
  gets that response even though its headers say `no-store`.
- A non-`GET` response keeps the `s-maxage` set at `api_utils.py:168` (e.g.
  `s-maxage=30` for `max_age=60`) next to `no-store`.
- `nosetests` (nose 1.x) does not start on Python 3.12:
  `ModuleNotFoundError: No module named 'imp'`.
- Six module doctests fail: `fmt_elapsed` calls the Python 2 `.next()`
  (`api_utils.py:485`, `:487`), and the `get_rel` examples need a request context and
  contain an unterminated string (`rule = '/v1`, `api_utils.py:639`).
- `python manage.py docs` calls `helpers/docs` (`manage.py:186`), which does not exist.

## License

[MIT](LICENSE) © Reuben Cummings
