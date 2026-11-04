---
source: ../../../../HDX/hdx-4w/README.md
---

# HDX-4W

Draft version of a 4W ("Who is doing What, Where, and When") visualization.
`index.html` uses dc.js, crossfilter, Leaflet and D3 to draw a "who" row
chart, a "what" row chart, a choropleth map ("where"), and a date-range
slider ("when"). The default configuration is titled
"La Nina Consortium 4W".

## Running

`js/hdx_site.js` loads its data files with `$.ajax`, so `index.html` must be
served over HTTP rather than opened from the filesystem. From this directory:

```bash
# Python 3
python3 -m http.server 8000

# or Python 2
python -m SimpleHTTPServer 8000
```

Then open <http://localhost:8000/index.html>.

## Data inputs

Both files are loaded from paths set in `def_config` (see below).

- `data/datastore_search.json`: a CKAN `datastore_search` API response.
  When `datatype` is `"datastore"`, the records are read from
  `result.records`. Each record must have these fields (names set in
  `def_config`):
  - `agency` (who)
  - `project_title` (what)
  - `county` (where; matched to the map case-insensitively)
  - `start_date` and `end_date` (when; parsed as `MM/DD/YYYY` unless
    `formatFieldName` is set)
- `data/geography.geojson`: the map geometry. Features are joined to the
  records on the `COUNTY_NAM` property.

## Configuration

Edit the `def_config` object at the top of `js/hdx_site.js`:

| Key | Default | Purpose |
| --- | --- | --- |
| `title` | `"La Nina Consortium 4W"` | Page title |
| `description` | `"Who is doing What, Where, and When in response to La Nina"` | Subtitle |
| `data` | `"data/datastore_search.json"` | URL of the 4W data |
| `whoFieldName` | `"agency"` | Record field for "who" |
| `whatFieldName` | `"project_title"` | Record field for "what" |
| `whereFieldName` | `"county"` | Record field for "where" |
| `startFieldName` | `"start_date"` | Record field for the start date |
| `endFieldName` | `"end_date"` | Record field for the end date |
| `geo` | `"data/geography.geojson"` | URL of the GeoJSON geometry |
| `joinAttribute` | `"COUNTY_NAM"` | GeoJSON property matched to `whereFieldName` |
| `nameAttribute` | `"COUNTY_NAM"` | GeoJSON property shown as the area name |
| `color` | `"#fdbe85"` | Chart and map highlight color |
| `enable4w` | `true` | Set in the config but not read by the code |
| `datatype` | `"datastore"` | If `"datastore"`, read records from `result.records` |

These optional keys are not in the default config but are read by the code:

- `formatFieldName`: a moment.js date format for the start and end fields
  (default `MM/DD/YYYY`).
- `geotype`: if `"datastore"`, the geometry response is unwrapped from
  `result.records`.

The date slider is shown only when both `startFieldName` and `endFieldName`
are set.

## Unused files

`index.html` loads only `js/hdx_site.js` and the libraries in `js/`. It does
not use `js/site.js`, `data/data.json`, or the root-level `data.json`,
`*.xlsx` and `*.csv` files.

## License

See [LICENSE](LICENSE) (MIT).
