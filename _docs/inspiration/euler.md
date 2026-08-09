<p align="center">
  <img src="logo.svg" alt="Euler" width="180">
</p>

# Euler

> **Status: concept / unimplemented.** This repository currently holds only the
> project vision and branding assets. No application code has been written here yet.
> The idea is documented in full in the Shuttleworth Foundation Fellowship application
> at [`media/shuttle.md`](media/shuttle.md).

Euler aims to be a suite of user-friendly, open-source products for **versioning,
sharing, and collaborating on tabular data — whether online or off**. Think of it as
the best parts of Git, Dropbox, and Google Docs, combined and focused on open data.

## The problem

Researchers and organizations that want to publish and collaborate on data hit the same
walls:

- **Offline vs. online.** Tools like Dropbox sync files but offer no data API and weak
  collaboration; Google Sheets collaborates well but isn't Excel-compatible and needs a
  connection. People end up writing scripts to bridge the gap.
- **Discoverability.** There are 2,500+ data portals worldwide, but the people who would
  benefit most from the data often never find it.
- **Reproducibility.** Many portals lack version history, so users upload redundant
  files named `dataset-5-25-15.csv`, `dataset-6-25-15.csv`, and so on.
- **Friction.** The dominant portal software (CKAN, Socrata) is hard to install, slow
  with large files, and weak on real-time and externally-hosted data.

## The vision

- **Work offline, sync automatically.** Edits made offline are stored locally and synced
  when a connection returns — without creating conflicted copies.
- **Real-time collaboration.** Saving a file notifies collaborators instantly; a web
  dashboard reflects everyone's changes live.
- **Effortless publishing.** Point Euler at a folder and it publishes to a searchable
  data portal, automatically incorporating data each time a file is created or saved.
- **Discoverable & reproducible.** Portals *push* their catalogs to a searchable index,
  data carries version history, and consumers can pin to and be notified about specific
  versions.
- **Programmatic access.** Well-documented APIs and conversion to/from multiple file
  formats.
- **GUI + CLI parity.** Every function is available from both a graphical interface and
  the command line, and the tools are cross-platform (Windows, macOS, Linux).

## Design

Euler is planned as three modular layers, so lower-level pieces can be swapped or
optimized without disrupting the applications built on top:

```
library  ->  framework  ->  application
```

- **Libraries** — building blocks (data processing, CKAN communication, etc.).
- **Frameworks** — self-hostable data management and aggregation built on the libraries.
- **Applications** — the web and command-line tools for versioning data and running
  searchable data portals.

## Related / underlying work

The vision draws on several existing open-source libraries by the author, which are
intended to power Euler's data analysis, portal communication, API generation, and
asynchronous processing:

- [meza](https://github.com/reubano/meza) — pure-Python data processing
- [ckanutils](https://github.com/reubano/ckanutils) — CKAN interaction
- [swutils](https://github.com/reubano/swutils)
- [hdxscraper data collectors](https://github.com/search?q=user%3Areubano+hdxscraper)
- [pipe2py (twisted)](https://github.com/kazeeki/pipe2py/tree/master/pipe2py/twisted)

## Repository contents

| Path | Description |
| ---- | ----------- |
| `media/shuttle.md` | Full Shuttleworth Foundation Fellowship application (project vision, plan, video script) |
| `media/` | Presentation decks, screenshots, and imagery |
| `logo.svg`, `Euler Title.svg`, `logo.icns`, `logo.tiff` | Branding assets |
| `state_of_internet.xlsx` | Supporting data referenced in the application |

## License

No license has been declared for this repository yet.
