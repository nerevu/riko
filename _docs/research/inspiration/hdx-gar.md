---
source: ../../../../HDX/gar/README.md
---

# gar

Scripts that split the UNISDR GAR15 global exposure dataset into one zip per country and
publish each zip as a dataset on HDX/CKAN.

The upstream dataset metadata is in `README - Metadata-Exposure2015.pdf`. `bin/split`
copies this PDF into every country zip.

## Requirements

- **bash 4.0+**. `create`, `update` and `rename` use `declare -A`, and `rename` also
  uses `${file::-4}` (bash 4.2+). macOS `/bin/bash` is 3.2. The scripts use
  `#!/usr/bin/env bash`, so a newer bash must come first on `PATH`.
- `ogr2ogr` (GDAL) and `zip` for `bin/split`.
- [ckanny](https://github.com/reubano/ckanny), hardcoded at
  `~/Documents/Projects/ckanny/bin/ckanny`.
- Env vars `CKAN_PROD_URL` and `CKAN_REMOTE_URL`. The scripts do not read an API key
  themselves. ckanny's own docs say it uses `CKAN_API_KEY` when it is set.
- `meza` (Python) for `geojsplit.py`.

Run everything from `gar/`. The scripts read `data/*.csv` and write zips relative to the
current directory.

## Scripts

| script | input | action |
|---|---|---|
| `bin/split` | `data/codes.csv` | For each ISO3: `ogr2ogr -where "iso3 = '<ISO>'" -nln gar_exp_<ISO> <ISO> shapefile gar_exp`. This reads layer `gar_exp` from `./shapefile/` (not included), copies `*.pdf` into `<ISO>/`, zips it to `<ISO>.zip`, then **`rm -fr <ISO>`**. |
| `bin/create [test]` | `data/codes.csv` | `ckanny pk.create`: creates "GAR15 Global Exposure Dataset for <country>" in org `united-nations-office-for-disaster-risk-reduction-unisdr`, with file `<ISO>.zip`, location (`-L`) = lowercase ISO3, plus fixed description, license, tags, methodology and caveats. |
| `bin/update [test]` | `data/codes.csv` | `ckanny pk.update`: updates the same metadata on the dataset whose slug comes from the title. |
| `bin/upload [test]` | `data/fix.csv` | `ckanny fs.upload -R <resource_id> <zip>`: replaces each resource's file. |
| `bin/rename [test]` | `data/fix.csv` | `ckanny fs.update -n "<title>.zip" <resource_id>`: renames each resource. |
| `bin/gcreate [prod]` | `exposure/gar_exp_AFG*.geojson` | `ckanny pk.create`: one "AFG GAR Exposure" dataset with every matching GeoJSON as a resource (`CNTRY="AFG"` is hardcoded). |

Target URL:

- `create`, `update`, `upload` and `rename` use `CKAN_PROD_URL` by default. Pass `test`
  as the first argument to use `CKAN_REMOTE_URL`.
- `gcreate` is the reverse. It uses `CKAN_REMOTE_URL` by default, and `prod` switches to
  `CKAN_PROD_URL`.
- Any other argument means the default.

## geojsplit.py

`geojsplit.py` is a library function, not a CLI. Its docstring gives the usage:

```python
from geojsplit import geojsplit
geojsplit('exposure/gar_exp.geojson', 'iso3', _id='_id5x')
```

It groups features by `key`, writing them to `<base>_<value>.csv` with mode `ab+`, so
running it again appends. It then re-reads those CSVs and writes
`<base>_<suffix>.geojson` files of at most `count` (default 8192) features each.

## data/

- `codes.csv`: no header, columns `iso3,n` (217 rows). The scripts use only `iso3`; `n`
  is `2` on every row.
- `fix.csv`: no header, columns `zip,package_id,resource_id` (217 rows), e.g.
  `ABW.zip,<uuid>,<uuid>`. `package_id` is not used.
- `tables.csv`: `title,table,start,end`. It lists Human Development Index indicator
  tables and is not used by any script here.

`ckanutils.egg-info/` is packaging metadata for ckanutils 0.14.10 and is not used by
these scripts.

## Known issues

- `bin/create` has `exit` inside its loop (line 301). It creates only the dataset for
  the first row of `codes.csv` and then stops.
- `bin/gcreate` runs `cd exposure`, but there is no `exposure/` directory. The `cd`
  fails and the script carries on in the current directory. `geojsplit.py`'s example
  path `exposure/gar_exp.geojson` does not exist either.
- `bin/split` needs `./shapefile/gar_exp.*`, which is not included.
