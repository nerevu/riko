---
source: ../../../../gcontact/README.md
---

# gcontact

## Introduction

gcontact is a Python client for the legacy Google Contacts **m8** feed
(`https://www.google.com/m8/feeds`). It downloads an account's contacts as JSON,
wraps each entry in a `Contact` object with typed properties (name, organization,
email, IM, group, website, photo, relation), and indexes them in a `Book` you can
look up by name, email, company, or contact key. A `Book` can also:

- import contacts from a CSV export (`Book.from_csv`);
- merge one book's contacts into another by exact or fuzzy (Simhash) matching
  (`match`/`update`), or merge near-duplicates within one book (`dedupe`);
- write changed contacts back to Google in Atom batch requests (`save`);
- enrich company records with web search, Facebook, Twitter, and Wikipedia data
  (`set_work_info`, `enrich_companies`).

**Note:** Google shut down the Contacts (m8) API in favor of the People API, so
this client no longer works against Google.

Everything lives in one module, `gcontact/__init__.py`, plus the helper
`gcontact/httpsession.py` (a `requests` session that keeps headers between calls).

## Requirements

gcontact requires **Python 3**. It imports `urllib.parse`, `html.parser`,
`json.JSONDecodeError`, and `types.SimpleNamespace`, none of which Python 2 has.

`setup.py` declares only `requests>=2.2.1`. The code also imports these packages, which
you have to install yourself:

| Package (PyPI name) | Used for |
|---|---|
| `requests` | HTTP session (`httpsession.py`) |
| `httplib2` | token refresh/authorization |
| `oauth2client` | OAuth client-secrets flow, service accounts, credential storage |
| `changanya` | `Simhash`/`SimhashIndex` for fuzzy matching and dedupe |
| `meza` | CSV reading, record merging, chunking |
| `mezmorize` | on-disk memoization of enrichment HTTP requests |
| `ijson` | streaming the JSON feed and the contact cache |
| `tqdm` | progress bars |
| `python-slugify` | keys for Wikipedia infobox rows |
| `beautifulsoup4` | parsing Wikipedia article HTML |
| `pygogo` | logging |

## Setup

### Installation

```sh
git clone git@github.com:reubano/gcontact.git
cd gcontact
pip install requests httplib2 oauth2client changanya meza mezmorize ijson tqdm python-slugify beautifulsoup4 pygogo
```

`gcontact/__init__.py` imports its sibling modules as top-level modules
(`from httpsession import HTTPSession`, `from exceptions import RequestError`), so
`import gcontact` fails with `ModuleNotFoundError` unless the inner `gcontact/`
directory is itself on `sys.path` (see Known issues). `pip install .` does not fix
this.

### Working directory

All cache files are read from and written to `caches/` **relative to the current
working directory**. Importing the module creates `caches/fetch/` there (the
`mezmorize` cache), so `caches/` always exists after import. Run gcontact from the
directory whose `caches/` you want to use (the repository root ships one).

### OAuth credentials

`Book(keyfile, ...)` calls `get_credentials(keyfile, **kwargs)`, which keeps one
credential file at `~/.credentials/gcontact.json` (it creates `~/.credentials/` if
needed). The OAuth scope is the m8 feed URL.

1. If a valid credential is stored there, it is used. If it has expired, or has no
   access token, it is refreshed.
2. Otherwise, if `keyfile` is given:
   - **client secrets (default):** `keyfile` is a client-secrets JSON file downloaded
     from the Google API console. gcontact runs the oauth2client `run_flow`
     browser/console flow and stores the result.
   - **service account:** pass `service_account=True`; `keyfile` is a service-account
     JSON key. Pass `account='user@example.com'` to act for that user through
     domain-wide delegation.
3. Pass `refresh=True` to ignore the stored credential and go through step 2 again.

The access token is sent as a `Bearer` header on every request.

## Configuration

### `Book` options

`Book(keyfile, **kwargs)` accepts these keyword arguments:

| Option | Default | Meaning |
|---|---|---|
| `user` | `$USER`, else `$USERNAME`, else `default` | The feed account is `'<user>@gmail.com'`. |
| `hash_keys` | `None` | `Contact` properties combined into match strings, e.g. `['names']` or `['emails']`. Set this, or pass `hash_keys=` to `match`/`update`; see Known issues. |
| `use_cache` | `True` | Load the etag and contacts from `caches/` when the book is built instead of from Google. |
| `cache_resp` | `True` | After fetching from Google, write the response to `caches/cache.json` and the etag to `caches/etag.json`. |
| `format` | `'json'` | Feed format. `'atom'` and `'rss'` pass validation but are not implemented; any other value raises `ValueError`. |
| `max_n` | `2048` | Contacts requested from Google, and contacts read from the cache. There is no paging. |
| `bits` | `2` | Largest Hamming distance between two Simhashes that still counts as a duplicate. |
| `ttl` | `7` | Days before `set_work_info`/`enrich_companies` look up a company or domain again. Does not affect the contact cache. |
| `industry_count` | `1` | Industries kept per company during enrichment. |
| `whois`, `websites`, `badsites` | `{}` | Base name of a JSON file in `caches/` to load the company, website, and rejected-site maps from (e.g. `whois='whois'` reads `caches/whois.json`). |
| `session` | new `HTTPSession` | HTTP session to use. |
| `verbose` | `None` | Debug logging; also makes `save` post batches one at a time instead of in parallel. |
| `monolog`, `formatter` | `True`, `None` | pygogo logging options. |
| `service_account`, `account`, `refresh` | | Passed to `get_credentials` (see OAuth credentials). |

### Environment variables

These are read once, when the module is imported. Only the enrichment methods use them.

| Variable | Used for |
|---|---|
| `YANDEX_API_USER`, `YANDEX_API_KEY` | Yandex XML web search for company websites |
| `FB_APP_ID`, `FB_APP_SECRET` | Facebook Graph API (v2.8) page lookups |
| `TWITTER_API_TOKEN` | Twitter API 1.1 `users/show` lookups |
| `USER`, `USERNAME` | default `user` (see above) |

### Cache files

| Path (relative to the working directory) | Written by | Read by | Expiry |
|---|---|---|---|
| `caches/etag.json` | `Book.etag` when `cache_resp` | `Book(...)` when `use_cache` | none |
| `caches/cache.json` | `Book.contacts` after a fetch from Google, when `cache_resp` | `Book(...)` when `use_cache` (at most `max_n` entries) | none |
| `caches/whois.json`, `websites.json`, `badsites.json` | `export(book, ...)` | `Book(whois=..., websites=..., badsites=...)` | entries are looked up again after `ttl` days |
| `caches/<name>.pickle` | `cache_book(book, name)` | `open_cached_book(name)` | none |
| `caches/fetch/` | memoized enrichment requests (`fetch`) | same | `2**30` seconds (about 34 years) |

A cached contact list is used whatever its age. To pull fresh contacts from Google,
build the book with `use_cache=False`.

## Usage

The examples need valid credentials and network access, so they show no output.

```python
from gcontact import Book

book = Book(
    'client_secret.json', use_cache=False, hash_keys=['names'], max_n=500)

len(book)                       # number of contacts loaded
contact = book['Jane Doe']      # first contact with that name, else that email
contact = book[0]               # by position
'jane@example.com' in book      # searches names, emails, and IM addresses

book.contacts_by_name['jane doe']           # list of Contacts, lowercase keys
book.contacts_by_email['jane@example.com']  # emails and IM addresses
book.contacts_by_company['acme']            # primary organization name
book.contacts_by_key[contact.clean_id]      # one Contact
getattr(book, contact.clean_id)             # same as above
```

### Lookups

| Lookup | Key | Returns |
|---|---|---|
| `book[value]` | name, else email (case-insensitive), else integer index or slice | the first match; `KeyError` if none |
| `getattr(book, key)` | `contact.clean_id` (`'_'` + the last part of the contact id) | the contact; `AttributeError` if none |
| `value in book` | exact name, email, or IM address | `bool` |
| `contacts_by_name` | each lowercase form in `contact.names` | `defaultdict(list)` |
| `contacts_by_email` | each lowercase email and IM address | `defaultdict(list)` |
| `contacts_by_company` | lowercase primary organization name, for contacts with a name | `defaultdict(list)` |
| `contacts_by_key` | `contact.clean_id` | `dict` |

The indexes are built on first access. `add` and `delete` reset the name, email, and
key indexes, but not `contacts_by_company`.

Other `Book` views: `names`, `emails`, `companies` (generators); `changed`/`unchanged`
and `matched`/`unmatched` (lists).

### Importing a CSV export

```python
linkedin = Book.from_csv('linkedin_connections.txt', hash_keys=['names'], max_n=1000)
```

`from_csv` reads a **tab-separated, UTF-16LE** file (`meza.io.read_tsv`) and maps the
columns `first`, `middle`, `last`, `company`, `title`, and `email` to a contact. The
contact id is the full name, company, title, and email joined with spaces. The book
is built with `use_cache=False` and no keyfile, so it relies on a credential already
stored in `~/.credentials/gcontact.json` (see Known issues).

### Matching another book

```python
book.match(linkedin, hash_keys=['names'], fuzzy=False)   # exact
book.match(linkedin, hash_keys=['emails'], fuzzy=False)
book.match(linkedin, hash_keys=['names'])                # fuzzy
book.save()
```

`match(other, hash_keys=None, fuzzy=True)` calls `update` for each **unmatched**
contact in `other`. `update(other_contact, hash_keys=None, fuzzy=False)` finds the
first contact in `book` that matches it:

- **exact:** a `book[...]` lookup on each match string;
- **fuzzy:** a Simhash index lookup within `bits` Hamming distance.

The first match absorbs the other contact (`_update`): the name, organization, and
email are replaced by the other contact's values when those are set and differ. The
old name and the other contact's note are appended to the note. The other contact
is marked `matched`.

Match strings come from `hash_keys`: every combination of the listed properties,
joined with spaces and lowercased. For example, `['names', 'emails']` produces one
string per name-and-email pair.

### Deduplicating a book

```python
for contact, other in book.find_dupes():
    print(contact, other)

book.dedupe(non_dupes={frozenset(['_abc123', '_def456'])})
```

- `find_dupes(contact=None, fuzzy=True, non_dupes=None)` with no `contact` yields
  pairs of contacts from changanya's `SimhashIndex.find_all_dupes`, skipping any pair
  of `clean_id`s in `non_dupes`. With a `contact`, it yields the book's matches for
  that one contact (exact or fuzzy, as in `update`).
- `find_dupes(fuzzy=False)` with no `contact` sets `book.bits = 0`. The change is
  permanent, so every later fuzzy lookup on the book only matches identical
  Simhashes (Hamming distance 0).
- `dedupe(fuzzy=True, non_dupes=None)` merges each pair's second contact into the
  first (same rules as `_update`) and removes the second from the book in memory.
  Nothing is deleted on Google: `Contact.delete` does nothing. Only the first contact's
  changes reach Google, through `save()`.
- `find_all_dupes` misses some duplicate pairs. For each block permutation it only
  compares hashes that share the masked prefix of the smallest permuted hash, so
  `dedupe` is not exhaustive.

### Saving

`save()` sends every **changed** contact to `<feed>/contacts/<account>/full/batch`:

- contacts are grouped into Atom batch feeds of `BATCH_SIZE = 100` entries, each
  entry being a `batch:operation type="update"` with the contact's etag;
- batches are posted in parallel on a thread pool (`multiprocessing.dummy`) with
  `min(batches, 2 × CPU count)` workers, or one at a time when `verbose` is set;
- it returns the responses (a list when `verbose`, otherwise an unordered iterator)
  and does not check their status.

A contact counts as changed when the Simhash of its name, emails, organizations, and
websites differs from the one computed when it was loaded. Edits to only the note,
phone, address, group, or relation do not make it changed, so `save` skips them.
`Contact.save()` PUTs one contact immediately.

`add(**fields)` builds a `Contact` from raw feed fields (`id` is required) and appends
it to the book in memory only: `Contact.create` does nothing, and `save` sends only
updates.

### Company enrichment

`set_work_info(enrich=False)` looks for each organization's website (Yandex search,
existing work website/email domains), sets the contact's `work_website` (which makes the
contact changed), and records results in `book.websites` and `book.badsites`.
`enrich_companies(update=False)` fills `book.whois` with network information from
Facebook, Twitter, and Wikipedia (`get_network_info`). Both skip entries looked up less
than `ttl` days ago. Save the maps with `export(book, 'book', cache=True)`.

## Data

### `Contact` fields

`Contact(account, session, **entry)` takes one JSON feed entry (`id` is required).

| Property | Read | Write (`contact.x = value`) |
|---|---|---|
| `name` | full name | replaces the name with a full name only |
| `names` | set of full name, "first last", and the name without " MD"/" PhD"/" CFA" | |
| `organization` | primary `"<title> at <org>"` | `"Title at Org"` or `"Org"`; becomes the primary organization |
| `organizations` | every `"<title> at <org>"` | |
| `email` / `emails` | primary / all addresses | sets the primary address; `rel` is work (domain matches the organization), home (gmail.com, yahoo.com, comcast.net), label School (`.edu`-like), or other |
| `work_email` | first work address | adds a work address |
| `im` / `ims` | primary / all IM addresses | `"protocol:address"` |
| `group` / `groups` | first / all group hrefs from memberships marked deleted | sets a membership |
| `website` / `websites` | primary / all hrefs | sets the primary website |
| `work_website` | first work website | adds a work website |
| `photo` | HTTP response for the photo, fetched once, if the contact has one | **PUTs immediately** (`del contact.photo` DELETEs immediately) |
| `relation` / `relations` | `"<rel>: <value>"` | sets a spouse relation |
| `note`, `title`, `nickname`, `birthday`, `gender`, `updated` | plain values | stored in feed form; any attribute assignment also updates `updated` |
| `phone`, `address` | raw feed lists (`address` includes structured addresses) | |
| `info` / `pretty_info` | summary dict / text | |
| `id`, `short_id`, `clean_id` | feed id, its last path part, `'_' + short_id` | |
| `changed`, `matched` | see Saving and Matching | |

## Intended API

The examples below show the intended API. None of these names (`Book(auth=)`, `open`,
`open_by_key`, `open_by_url`, `share`, `sheet1`, `worksheet`, `acell`, `range`,
`update_cells`, `find`/`findall`) exist in the current code; for what it provides, see
[Usage](#usage).

<a href="https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=TK7NPLQ6XEPKS&lc=US&item_name=gcontact&currency_code=USD&bn=PP%2dDonationsBF%3abtn_donate_LG%2egif%3aNonHosted" target="_blank"><img src="https://www.paypalobjects.com/en_US/i/btn/btn_donate_LG.gif" /></a>

Manage your contacts with _gcontact_ in Python.

Manage your contacts with _gcontact_ in Python.

Features:

- Open a contact by its **title** or **url**.
- Extract range, entire row or column values.
- Independent of Google Data Python client library.
- Python 3 support.

### Basic Usage

1. [Obtain OAuth2 credentials from Google Developers Console](http://gcontact.readthedocs.org/en/latest/oauth2.html)

2. Start using gcontact:

```python
import gcontact

gc = gcontact.Book(auth=OAuthCredentialObject)

# Open a worksheet from contact with one shot
wks = gc.open("Where is the money Lebowski?").sheet1

wks.update_acell("B2", "it's down there somewhere, let me take another look.")

# Fetch a cell range
cell_list = wks.range("A1:B7")
```

### More Examples

#### Opening a Contact

```python
# You can open a contact by its title as it appears in Google Docs
sh = gc.open("My poor gym results")  # <-- Look ma, no keys!

# If you want to be specific, use a key (which can be extracted from
# the contact's url)
sht1 = gc.open_by_key("0BmgG6nO_6dprdS1MN3d3MkdPa142WFRrdnRRUWl1UFE")

# Or, if you feel really lazy to extract that key, paste the entire url
sht2 = gc.open_by_url("https://docs.google.com/contact/ccc?key=0Bm...FE&hl")
```

#### Creating a Contact

```python
sh = gc.create("A new contact")

# But that new contact will be visible only to your script's account.
# To be able to access newly created contact you *must* share it
# with your email. Which brings us to…
```

#### Sharing a Contact

```python
sh.share("otto@example.com", perm_type="user", role="writer")
```

#### Selecting a Worksheet

```python
# Select worksheet by index. Worksheet indexes start from zero
worksheet = sh.get_worksheet(0)

# By title
worksheet = sh.worksheet("January")

# Most common case: Sheet1
worksheet = sh.sheet1

# Get a list of all worksheets
worksheet_list = sh.worksheets()
```

#### Creating a Worksheet

```python
worksheet = sh.add_worksheet(title="A worksheet", rows="100", cols="20")
```

#### Deleting a Worksheet

```python
sh.del_worksheet(worksheet)
```

#### Getting a Cell Value

```python
# With label
val = worksheet.acell("B1").value

# With coords
val = worksheet.cell(1, 2).value

# To get a cell formula
cell = worksheet.acell("B1")  # or .cell(1, 2)
cell.input_value
```

#### Getting All Values From a Row or a Column

```python
# Get all values from the first row
values_list = worksheet.row_values(1)

# Get all values from the first column
values_list = worksheet.col_values(1)
```

#### Getting All Values From a Worksheet as a List of Lists

```python
list_of_lists = worksheet.get_all_values()
```

#### Finding a Cell

```python
# Find a cell with exact string value
cell = worksheet.find("Dough")

print("Found something at R%sC%s" % (cell.row, cell.col))

# Find a cell matching a regular expression
amount_re = re.compile(r"(Big|Enormous) dough")
cell = worksheet.find(amount_re)
```

#### Finding All Matched Cells

```python
# Find all cells with string value
cell_list = worksheet.findall("Rug store")

# Find all cells with regexp
criteria_re = re.compile(r"(Small|Room-tiering) rug")
cell_list = worksheet.findall(criteria_re)
```

#### Cell Object

Each cell has a value and coordinates properties.

```python
value = cell.value
row_number = cell.row
column_number = cell.col
```

#### Updating Cells

```python
worksheet.update_acell("B1", "Bingo!")

# Or
worksheet.update_cell(1, 2, "Bingo!")

# Select a range
cell_list = worksheet.range("A1:C7")

for cell in cell_list:
    cell.value = "O_o"

# Update in batch
worksheet.update_cells(cell_list)
```

### Documentation

- [Getting Google API's credentials](http://gcontact.readthedocs.io/en/latest/oauth2.html)
- [gcontact API Reference](http://gcontact.readthedocs.org/)

### [Contributors](https://github.com/burnash/gcontact/graphs/contributors)

### How to Contribute

#### Ask Questions

The best way to get an answer to a question is to ask on
[Stack Overflow with a gcontact tag](http://stackoverflow.com/questions/tagged/gcontact?sort=votes&pageSize=50).

#### Report Issues

Please report bugs and suggest features via the
[GitHub Issues](https://github.com/burnash/gcontact/issues).

Before opening an issue, search the tracker for possible duplicates. If you find a
duplicate, please add a comment saying that you encountered the problem as well.

#### Contribute code

- Check the [GitHub Issues](https://github.com/burnash/gcontact/issues) for open issues
  that need attention.
- Follow the
  [Contributing to Open Source](https://guides.github.com/activities/contributing-to-open-source/)
  Guide.

## Testing

`tests/test.py`, `tests/mock_tests.py`, and `tests/tests.config.example` were written
for gspread: they build `Book(auth=...)` and call `open`, `open_by_key`, and worksheet
methods that this code does not have. No test in the repository exercises the current
API.

The intended test workflow:

1. Go to Google Drive and create an empty contact you will use for testing.
2. Create a configuration file from config dummy:

    ```sh
    cp tests/tests.config.example tests/tests.config
    ```

3. Open `tests.config` with your favorite editor and fill up config parameters with your
   testing contact's info.
4. Install [Nose](http://nose.readthedocs.org).
5. Run tests:

    ```sh
    nosetests
    ```

## Known issues

- `import gcontact` fails unless `gcontact/gcontact/` is on `sys.path`, because the
  package imports its own modules as top-level modules
  (`gcontact/__init__.py:46-47`, `gcontact/httpsession.py:20`, `gcontact/utils.py:13`).
- `setup.py` lists only `requests`. Every other dependency in Requirements is missing
  from `install_requires` (`setup.py:47`). `setup.py` and `LICENSE.txt` still name the
  gspread author and the `burnash/gcontact` URL (`setup.py:41-44`), and
  `docs/index.txt`, which becomes the package description, is gspread's text.
- With the default `use_cache=True` and no `caches/cache.json`, the book loads zero
  contacts and never asks Google, because the empty cache result is stored and
  `contacts` fetches only when it is `None` (`gcontact/__init__.py:1975-1987`,
  `:2059`). Use `use_cache=False` for the first run.
- Without `Book(hash_keys=...)`, every contact gets `hash_keys=None` and building its
  Simhashes raises `TypeError` (`gcontact/__init__.py:1234`, `:1997-1999`, `:1321`).
  `find_dupes()` and `dedupe()` always crash then; `match` and fuzzy `update` crash
  unless the call passes `hash_keys=` (`:2424-2426`, `:2437`, `:2448`).
- `format='atom'` or `'rss'` passes the format check but raises `NotImplementedError`
  when contacts are loaded, from the cache or from Google
  (`gcontact/__init__.py:1970`, `:669-671`, `:2073-2075`).
- `Book.from_csv` raises `AttributeError` when no credential is stored yet, because
  `get_credentials(None)` reads `.access_token` from `None`
  (`gcontact/__init__.py:2023`, `:756`).
- `Contact.create` and `Contact.delete` are empty, so `Book.add` never creates a contact
  on Google, and `Book.delete`, `del book[...]`, and `dedupe` never delete one
  (`gcontact/__init__.py:1864-1869`, `:1879-1884`).
- `Book.add` raises `KeyError` without an `id` field (`gcontact/__init__.py:1200`), and
  raises `AttributeError` when the contacts have not been loaded yet (`:2384`).
- `find_dupes(fuzzy=False)` permanently sets `book.bits = 0`
  (`gcontact/__init__.py:2359-2360`).
- `dedupe` misses pairs because changanya's `find_all_dupes` only scans the
  smallest-hash prefix group of each permutation (`changanya/simhash.py:228-230`).
- `save` only detects changes to name, email, organization, and website
  (`gcontact/__init__.py:828-830`, `:1335-1345`) and ignores response status codes
  (`:2117-2142`).
- `groups` yields only memberships whose `deleted` flag is not `'false'`, and
  `del contact.group` sets that flag to `'false'` (`gcontact/__init__.py:1527-1545`).
- Reading `contact.photo` sends the default `Content-Type: application/json` header, so
  `HTTPSession` decodes the image body as JSON (`gcontact/__init__.py:1623`,
  `gcontact/httpsession.py:23`, `:98-99`).
- `Contact.info` reports the email values under `im` and `ims`
  (`gcontact/__init__.py:1677`, `:1680`).
- The `im` setter's protocol check is inverted (`if not protocol not in
  IM_PROTOCOLS`). Unknown protocols are stored as typed instead of raising
  `ValueError` (`gcontact/__init__.py:1501-1508`).
- The `relation` setter compares against `relation['href']`, which relation entries
  (`rel`/`$t`) do not have, so it raises `KeyError` when the contact already has a
  relation (`gcontact/__init__.py:1667`).
- Running the module as a script (`python gcontact/__init__.py`, where the implicit
  imports do resolve) runs `main()`. It is
  hard-coded to one personal setup: keyfile `~/client-secret-MCvgr.json`,
  `max_n=2479`, a fixed `non_dupes` pair (`gcontact/__init__.py:3663-3700`, `:3784`).

## License

gcontact is distributed under the MIT License; see `LICENSE.txt`.
