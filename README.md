# Kolibri Curriculum Catalog

A standalone Python project that imports **curriculum metadata** through Kolibri,
exports the hierarchy to JSON, and maintains a queryable SQLite catalog for study
planning and future AI-agent integration.

The project deliberately does **not** scrape Khan Academy pages and does **not**
download videos, exercise payloads, documents, thumbnails, or quiz data. It runs
Kolibri's `importchannel` operation only, then reads the imported channel database
in read-only mode.

> **Normal users never need to find, copy, or type a Kolibri channel ID.**
> The CLI resolves educational sources by name and language.
> Raw channel IDs remain part of the internal data model but are not required for
> ordinary use.

## Quick Start

```bash
# List available educational sources
curriculum sources

# Filter by language
curriculum sources --language vi

# Search by name
curriculum sources --search khan

# Inspect a source
curriculum source show "Khan Academy"

# List available languages for a source
curriculum source languages "Khan Academy"

# Sync a source by name and language
curriculum sync "Khan Academy" --language en

# If a source has only one language, the flag may be omitted
curriculum sync "MIT BLOSSOMS"

# Tree view
curriculum query --db data/catalog.sqlite3 subtree CHANNEL_ID NODE_ID

# Search across imported content
curriculum query --db data/catalog.sqlite3 search "quadratic equations"

# Search within a specific source
curriculum query --db data/catalog.sqlite3 search "linear equations" \
  --source "Khan Academy" --language en
```

## What it produces

For each synchronized channel:

```text
data/
├── catalog.sqlite3
├── exports/
│   └── <channel-id>/
│       └── current/
│           ├── manifest.json
│           ├── nodes.jsonl
│           ├── outline.json
│           ├── catalog.json
│           └── lessons.json
└── snapshots/
    └── <channel-id>/
        └── 20260806T100000Z/
            └── ...same JSON files...
```

The files serve different purposes:

- `manifest.json`: channel metadata, node counts, kinds, and maximum depth.
- `nodes.jsonl`: one normalized source node per line; best for scripts and diffs.
- `outline.json`: topic-only nested hierarchy.
- `catalog.json`: complete nested metadata hierarchy, including resource metadata.
- `lessons.json`: planning-oriented records with inferred subject/course/unit/lesson
  fields plus authoritative `node_id` and `source_path` values.
- `catalog.sqlite3`: current nodes, snapshots, and added/modified/moved/removed changes.

## Why both source hierarchy and planning view exist

Kolibri stores channel structure as generic content nodes. Channels are free to use
different nesting depths, so the project never assumes that every source follows a
fixed `Subject -> Course -> Unit -> Lesson` schema.

The authoritative representation is always:

```text
node_id + parent_id + kind + source path
```

`lessons.json` additionally infers labels such as `course`, `unit`, and `lesson` for
study-planning convenience. For example:

```json
{
  "course": "Algebra 1",
  "unit": "Unit 6",
  "lesson": "Lesson 1",
  "item": "Graphing systems of equations",
  "item_type": "video",
  "about": "Sal graphs the following system of equations...",
  "author": "Sal Khan",
  "node_id": "...",
  "source_path": [
    "Math",
    "Algebra 1",
    "Unit 6",
    "Lesson 1",
    "Graphing systems of equations"
  ]
}
```

Only metadata is exported. The `video` kind above describes a catalog item; the
video file itself is never read or downloaded by this project.

## Requirements

- Python 3.11 or newer
- Kolibri installed and able to access Kolibri Studio for the initial channel import

Kolibri's documentation distinguishes channel database import from content import:
`importchannel` downloads the channel database, while `importcontent` downloads
resource files. This project uses only `importchannel`.

Official references:

- Kolibri command-line guide:
  <https://kolibri.readthedocs.io/en/latest/manage/command_line.html>
- Kolibri data-directory layout:
  <https://kolibri.readthedocs.io/en/latest/manage/provision.html>
- Kolibri content model source:
  <https://github.com/learningequality/kolibri/blob/develop/kolibri/core/content/base_models.py>

## Installation

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install Kolibri:

```bash
python -m pip install kolibri
```

Install this project:

```bash
python -m pip install -e .
```

For development and tests:

```bash
python -m pip install -e '.[dev]'
pytest
```

## Discovering Educational Sources

The CLI maintains a local cache of educational sources at
`~/.cache/curriculum/sources.json`. This cache must be populated by a discovery
backend before source names can be resolved.

### Listing sources

```bash
curriculum sources
```

Example output:

```text
Available educational sources

SOURCE                       LANGUAGES              CHANNELS
Khan Academy                 en, vi, es, fr              8
CK-12                        en                          3
OpenStax                     en, es                      4
PhET                         en, vi, es, fr             20
MIT BLOSSOMS                 en                          1
```

Filter by language:

```bash
curriculum sources --language vi
```

Search by name:

```bash
curriculum sources --search khan
```

Machine-readable output:

```bash
curriculum sources --json
```

Refresh the discovery catalog from the network:

```bash
curriculum sources --refresh
```

### Inspecting a source

```bash
curriculum source show "Khan Academy"
```

```bash
curriculum source languages "Khan Academy"
```

```bash
curriculum source channels "Khan Academy"
```

With internal channel IDs (advanced):

```bash
curriculum source show "Khan Academy" --ids
curriculum source channels "Khan Academy" --ids
```

### Cache behavior

| Cache state | Network | Result |
|-------------|---------|--------|
| Fresh       | any     | Use cache |
| Stale       | available | Refresh and save |
| Stale       | unavailable | Use stale cache (warns) |
| Missing     | unavailable | Error with guidance |

The cache is considered fresh for 7 days. Run `curriculum sources --refresh` to update
it explicitly.

### Offline usage

Commands that query already-imported data work without network access:

```bash
curriculum query --db data/catalog.sqlite3 channels
curriculum query --db data/catalog.sqlite3 search "algebra"
curriculum query --db data/catalog.sqlite3 changes
```

Source discovery requires network access only when refreshing the cache.

## Syncing by Source Name

The primary sync command accepts an educational source name and language:

```bash
curriculum sync "Khan Academy" --language en
curriculum sync "OpenStax" --language en
curriculum sync "PhET" --language vi
```

If a source is available in only one language, the `--language` flag may be omitted:

```bash
curriculum sync "MIT BLOSSOMS"
```

### Multiple language variants

If a source supports multiple languages and `--language` is omitted:

```text
Khan Academy is available in multiple languages:

  en  English
  es  Spanish
  fr  French
  vi  Vietnamese

Specify one with:
  curriculum sync "Khan Academy" --language en
```

### Multiple channel variants

Some sources publish several channels for the same language:

```text
Multiple English Khan Academy channels are available.

VARIANT
General
US Curriculum
Philippines Curriculum

Specify one with:
  --variant "US Curriculum"
```

Then:

```bash
curriculum sync "Khan Academy" --language en --variant "US Curriculum"
```

### Skip network import

To process an already-imported database without network access:

```bash
curriculum sync "Khan Academy" --language en --skip-import
```

## Source Aliases

Sources can be looked up by alias as well as full name:

| Full name       | Aliases              |
|-----------------|----------------------|
| Khan Academy    | `khan`, `ka`         |
| MIT BLOSSOMS    | `blossoms`, `mit blossoms` |
| PhET            | `phet simulations`   |
| OpenStax        | `open stax`          |
| Blockly Games   | `blockly`            |
| HP LIFE         | `hp life`            |

Example:

```bash
curriculum sync "khan" --language en
```

Alias matching is exact and deterministic. No AI/fuzzy matching is used.

## Query SQLite

List channels:

```bash
curriculum query --db data/catalog.sqlite3 channels
```

Search titles, descriptions, and paths across all channels:

```bash
curriculum query --db data/catalog.sqlite3 search "systems of equations"
```

Search within a specific source (resolves name to channel ID):

```bash
curriculum query --db data/catalog.sqlite3 search "systems of equations" \
  --source "Khan Academy" --language en
```

Read one node:

```bash
curriculum query --db data/catalog.sqlite3 node CHANNEL_ID NODE_ID
```

List roots or children:

```bash
curriculum query --db data/catalog.sqlite3 children CHANNEL_ID root
curriculum query --db data/catalog.sqlite3 children CHANNEL_ID PARENT_NODE_ID
```

Read a bounded subtree:

```bash
curriculum query --db data/catalog.sqlite3 subtree CHANNEL_ID NODE_ID --max-depth 3
```

Review detected curriculum changes:

```bash
curriculum query --db data/catalog.sqlite3 changes \
  --source "Khan Academy" --language en
```

## Python API

```python
from kolibri_curriculum.repository import CatalogRepository

repo = CatalogRepository("data/catalog.sqlite3")

channels = repo.list_channels()
results = repo.search("linear equations", channel_id="CHANNEL_ID", limit=20)
```

Source-aware agent API:

```python
from kolibri_curriculum.agent_api import CatalogQueryService
from kolibri_curriculum.discovery import FileCacheDiscovery

catalog = CatalogQueryService(
    "data/catalog.sqlite3",
    discovery=FileCacheDiscovery(),
)

# List sources
sources = catalog.sources()

# Resolve a source to a channel ID
resolved = catalog.resolve_source("Khan Academy", language="en")
channel_id = resolved["channel_id"]

# Search within a source
results = catalog.search_source("quadratic equations", "Khan Academy", language="en")
```

See [AGENTS.md](AGENTS.md) for the next milestone.

## Periodic Updates

Example monthly cron entry (first Sunday at 03:15):

```cron
15 3 1-7 * 0 cd /opt/curriculum && .venv/bin/curriculum sync "Khan Academy" --language en >> data/refresh.log 2>&1
```

To sync multiple configured sources:

```bash
curriculum sync "Khan Academy" --language en
curriculum sync "OpenStax" --language en
curriculum sync "PhET" --language vi
```

Each run stores a timestamped JSON snapshot and records changes in SQLite:

- `added`
- `modified`
- `moved`
- `removed`
- `unchanged`

Removed nodes remain in SQLite with `is_active = 0`, preserving references from future
study plans.

## Advanced Usage

> The following options are intended for development, debugging, and internal tooling.
> They are not required for normal use.

### Import a channel by ID directly

```bash
curriculum import-channel YOUR_CHANNEL_ID
curriculum import-channel YOUR_CHANNEL_ID --kolibri-command "python -m kolibri"
```

### Sync by channel ID (deprecated pattern)

```bash
curriculum sync --channel-id YOUR_CHANNEL_ID --data-dir ./data
```

A deprecation warning is shown. Prefer the source-name form.

### Discover imported databases

```bash
curriculum discover
curriculum discover --kolibri-home /srv/kolibri
```

### Export an arbitrary channel database

```bash
curriculum export ~/.kolibri/content/databases/CHANNEL_DATABASE.sqlite3 --output ./export
curriculum export CHANNEL_DATABASE.sqlite3 --output ./export --include-kinds topic,video,exercise
```

## Data and Legal Boundaries

This project is intended for private curriculum planning and metadata management.
It does not bypass access controls, scrape the live Khan Academy website, or download
lesson resources.

Review the current terms and licenses of Khan Academy, Kolibri, and each imported
channel before redistribution or commercial use. Node-level license fields are retained
in the catalog when provided by the channel database.

## Limitations

- Course/unit/lesson names in `lessons.json` are inferred from titles and ancestry.
  `source_path` is authoritative.
- Kolibri channel schemas can evolve. The reader uses schema introspection instead of
  a single hard-coded table layout, but a future incompatible schema may require an
  adapter.
- Some descriptions may be blank because the source channel does not supply them.
- This project does not determine pedagogical prerequisites by itself.
- No study-plan write model is included yet; that is the next agent milestone.

## Project Documents

- [ARCHITECTURE.md](ARCHITECTURE.md): components, data model, synchronization, and
  compatibility strategy.
- [AGENTS.md](AGENTS.md): engineering rules and the milestone for safe agent access.


For each synchronized channel:

```text
data/
├── catalog.sqlite3
├── exports/
│   └── <channel-id>/
│       └── current/
│           ├── manifest.json
│           ├── nodes.jsonl
│           ├── outline.json
│           ├── catalog.json
│           └── lessons.json
└── snapshots/
    └── <channel-id>/
        └── 20260806T100000Z/
            └── ...same JSON files...
```

The files serve different purposes:

- `manifest.json`: channel metadata, node counts, kinds, and maximum depth.
- `nodes.jsonl`: one normalized source node per line; best for scripts and diffs.
- `outline.json`: topic-only nested hierarchy.
- `catalog.json`: complete nested metadata hierarchy, including resource metadata.
- `lessons.json`: planning-oriented records with inferred subject/course/unit/lesson
  fields plus authoritative `node_id` and `source_path` values.
- `catalog.sqlite3`: current nodes, snapshots, and added/modified/moved/removed changes.

## Why both source hierarchy and planning view exist

Kolibri stores channel structure as generic content nodes. Channels are free to use
different nesting depths, so the project never assumes that every source follows a
fixed `Subject -> Course -> Unit -> Lesson` schema.

The authoritative representation is always:

```text
node_id + parent_id + kind + source path
```

`lessons.json` additionally infers labels such as `course`, `unit`, and `lesson` for
study-planning convenience. For example:

```json
{
  "course": "Algebra 1",
  "unit": "Unit 6",
  "lesson": "Lesson 1",
  "item": "Graphing systems of equations",
  "item_type": "video",
  "about": "Sal graphs the following system of equations...",
  "author": "Sal Khan",
  "node_id": "...",
  "source_path": [
    "Math",
    "Algebra 1",
    "Unit 6",
    "Lesson 1",
    "Graphing systems of equations"
  ]
}
```

Only metadata is exported. The `video` kind above describes a catalog item; the
video file itself is never read or downloaded by this project.

## Requirements

- Python 3.11 or newer
- Kolibri installed and able to access Kolibri Studio for the initial channel import
- A Kolibri channel ID

Kolibri's documentation distinguishes channel database import from content import:
`importchannel` downloads the channel database, while `importcontent` downloads
resource files. This project uses only `importchannel`.

Official references:

- Kolibri command-line guide:
  <https://kolibri.readthedocs.io/en/latest/manage/command_line.html>
- Kolibri data-directory layout:
  <https://kolibri.readthedocs.io/en/latest/manage/provision.html>
- Kolibri content model source:
  <https://github.com/learningequality/kolibri/blob/develop/kolibri/core/content/base_models.py>

## Installation

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install Kolibri:

```bash
python -m pip install kolibri
```

Install this project:

```bash
python -m pip install -e .
```

For development and tests:

```bash
python -m pip install -e '.[dev]'
pytest
```

## Find the channel ID

Use Kolibri's web interface:

```bash
kolibri start
```

Open the local Kolibri interface, go to the device channel-import screen, locate the
Khan Academy channel you need, and copy its channel ID.

Channel IDs are not hard-coded in this repository because language and curriculum
channels may be replaced or republished.

## Import metadata only

```bash
kcurriculum import-channel YOUR_CHANNEL_ID
```

Equivalent Kolibri command:

```bash
kolibri manage importchannel network YOUR_CHANNEL_ID
```

Do not run `importcontent` for this metadata-only workflow.

When Kolibri is installed under a Python module launcher rather than a console
script, specify the command prefix:

```bash
kcurriculum import-channel YOUR_CHANNEL_ID \
  --kolibri-command "python -m kolibri"
```

## Discover imported channel databases

```bash
kcurriculum discover
```

By default, the project looks under:

```text
~/.kolibri/content/databases/
```

Override the home directory with either:

```bash
export KOLIBRI_HOME=/srv/kolibri
```

or:

```bash
kcurriculum discover --kolibri-home /srv/kolibri
```

## Full synchronization

The normal command refreshes the Kolibri channel database, reads it, exports JSON,
and updates SQLite:

```bash
kcurriculum sync \
  --channel-id YOUR_CHANNEL_ID \
  --data-dir ./data
```

For a Kolibri module launcher:

```bash
kcurriculum sync \
  --channel-id YOUR_CHANNEL_ID \
  --data-dir ./data \
  --kolibri-command "python -m kolibri"
```

To process an already imported database without network access:

```bash
kcurriculum sync \
  --channel-id YOUR_CHANNEL_ID \
  --database ~/.kolibri/content/databases/CHANNEL_DATABASE.sqlite3 \
  --skip-import \
  --data-dir ./data
```

To limit only the nested JSON tree display depth while retaining the complete SQLite
catalog and planning records:

```bash
kcurriculum sync \
  --channel-id YOUR_CHANNEL_ID \
  --max-depth 6
```

## Export an arbitrary channel database

```bash
kcurriculum export \
  ~/.kolibri/content/databases/CHANNEL_DATABASE.sqlite3 \
  --output ./export
```

Filter source node kinds when needed:

```bash
kcurriculum export CHANNEL_DATABASE.sqlite3 \
  --output ./export \
  --include-kinds topic,video,exercise
```

Filtering can disconnect a child from an excluded parent, so the unfiltered export is
recommended for reliable paths and hierarchy.

## Query SQLite

List channels:

```bash
kcurriculum query --db data/catalog.sqlite3 channels
```

Search titles, descriptions, and paths:

```bash
kcurriculum query --db data/catalog.sqlite3 search "systems of equations" \
  --channel-id YOUR_CHANNEL_ID
```

Read one node:

```bash
kcurriculum query --db data/catalog.sqlite3 node \
  YOUR_CHANNEL_ID NODE_ID
```

List roots or children:

```bash
kcurriculum query --db data/catalog.sqlite3 children YOUR_CHANNEL_ID root
kcurriculum query --db data/catalog.sqlite3 children YOUR_CHANNEL_ID PARENT_NODE_ID
```

Read a bounded subtree:

```bash
kcurriculum query --db data/catalog.sqlite3 subtree \
  YOUR_CHANNEL_ID NODE_ID --max-depth 3
```

Review detected curriculum changes:

```bash
kcurriculum query --db data/catalog.sqlite3 changes \
  --channel-id YOUR_CHANNEL_ID --limit 100
```

## Python API

```python
from kolibri_curriculum.repository import CatalogRepository

repo = CatalogRepository("data/catalog.sqlite3")

channels = repo.list_channels()
results = repo.search(
    "linear equations",
    channel_id="YOUR_CHANNEL_ID",
    limit=20,
)
children = repo.list_children("YOUR_CHANNEL_ID", "PARENT_NODE_ID")
subtree = repo.get_subtree(
    "YOUR_CHANNEL_ID",
    "COURSE_NODE_ID",
    max_depth=4,
)
```

A restricted read-only facade intended for future agent tools is also provided:

```python
from kolibri_curriculum.agent_api import CatalogQueryService

catalog = CatalogQueryService("data/catalog.sqlite3")
context = catalog.search("quadratic equations", channel_id="YOUR_CHANNEL_ID")
```

See [AGENTS.md](AGENTS.md) for the next milestone.

## Periodic updates

A wrapper script is included:

```bash
CHANNEL_ID=YOUR_CHANNEL_ID ./scripts/refresh.sh
```

Example monthly cron entry, at 03:15 on the first Sunday:

```cron
15 3 1-7 * 0 cd /opt/kolibri-curriculum && CHANNEL_ID=YOUR_CHANNEL_ID .venv/bin/kcurriculum sync --channel-id "$CHANNEL_ID" --data-dir ./data >> ./data/refresh.log 2>&1
```

Each run stores a timestamped JSON snapshot and records changes in SQLite:

- `added`
- `modified`
- `moved`
- `removed`
- `unchanged`

Removed nodes remain in SQLite with `is_active = 0`, preserving references from future
study plans.

## Data and legal boundaries

This project is intended for private curriculum planning and metadata management.
It does not bypass access controls, scrape the live Khan Academy website, or download
lesson resources.

Review the current terms and licenses of Khan Academy, Kolibri, and each imported
channel before redistribution or commercial use. Node-level license fields are retained
in the catalog when provided by the channel database.

## Limitations

- Course/unit/lesson names in `lessons.json` are inferred from titles and ancestry.
  `source_path` is authoritative.
- Kolibri channel schemas can evolve. The reader uses schema introspection instead of
  a single hard-coded table layout, but a future incompatible schema may require an
  adapter.
- Some descriptions may be blank because the source channel does not supply them.
- This project does not determine pedagogical prerequisites by itself.
- No study-plan write model is included yet; that is the next agent milestone.

## Project documents

- [ARCHITECTURE.md](ARCHITECTURE.md): components, data model, synchronization, and
  compatibility strategy.
- [AGENTS.md](AGENTS.md): engineering rules and the milestone for safe agent access.
