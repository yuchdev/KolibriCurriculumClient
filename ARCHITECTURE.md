# Architecture

## 1. Goal

The system builds a local, updateable curriculum catalog from a Kolibri channel
database. It targets study-path planning rather than content playback.

The system must:

1. obtain curriculum metadata through Kolibri;
2. preserve the source tree at arbitrary depth;
3. export human- and machine-readable JSON;
4. maintain a normalized SQLite catalog;
5. detect changes between imports;
6. expose a bounded query interface suitable for a later AI agent;
7. avoid downloading or parsing content resources.

## 2. System boundary

```text
User source reference ("Khan Academy", language="en")
          |
          v
    SourceResolver
          |
          +-----> Provider Registry (source_registry.py)
          |
          +-----> Channel Discovery Cache (discovery.py)
          |
          v
    Resolved Channel (channel_id)
          |
          v
Kolibri Studio / channel source
          |
          | kolibri manage importchannel network <channel-id>
          v
KOLIBRI_HOME/content/databases/<channel-db>
          |
          | read-only SQLite access
          v
kolibri_curriculum.reader
          |
          +-------------------+
          |                   |
          v                   v
JSON exporters          CatalogRepository
          |                   |
          v                   v
snapshots/current       catalog.sqlite3
                              |
                              v
                    CatalogQueryService
                    (agent tools + source-aware API)
```

The project never invokes `importcontent`. It does not read Kolibri's
`content/storage` directory.

Channel IDs remain authoritative internally. Source names and languages are a UX
layer that resolves to channel IDs before any Kolibri operation.

## 3. Modules

### `source_registry.py`

Defines `SourceDefinition` — a known educational content provider with a stable
`provider_id`, a human-readable `display_name`, and a tuple of `aliases`.

The registry lists providers such as Khan Academy, CK-12, OpenStax, and PhET.
It does **not** store volatile Kolibri channel IDs.

Resolution priority:

1. Exact display name (case-insensitive).
2. Exact provider ID.
3. Known alias.
4. Unique partial substring match of display name.
5. Ambiguity error (multiple matches) or not-found error (zero matches).

### `discovery.py`

Defines `DiscoveredChannel` — a channel found through a discovery source — and the
`ChannelDiscovery` protocol that any backend must satisfy.

Concrete implementations:

- `NullDiscovery`: returns a fixed list; used in tests and offline mode.
- `FileCacheDiscovery`: reads a local JSON cache (`~/.cache/curriculum/sources.json`).
  May delegate to a live backend when the cache is absent or stale.

Cache behavior:

| State              | Network     | Outcome                              |
|--------------------|-------------|--------------------------------------|
| Fresh (< 7 days)   | any         | Use cache                            |
| Stale (≥ 7 days)   | available   | Refresh and save                     |
| Stale (≥ 7 days)   | unavailable | Use stale cache (emits warning)      |
| Missing            | unavailable | Raise `RuntimeError` with guidance   |

Language helpers: `resolve_language_code` converts full names (e.g. "English") to
codes (e.g. "en"), and `language_display_name` does the reverse.

### `resolver.py`

Implements `SourceResolver` — the service that maps a human source name + language
(+ optional variant) to a `ResolvedChannel` containing a stable `channel_id`.

Resolution flow:

```text
"Khan Academy" + language="en" + variant="US Curriculum"
        |
        v
 resolve_source() -> SourceDefinition
        |
        v
 filter DiscoveredChannel list by provider_id + language
        |
        v
 variant filter (if multiple channels for that language)
        |
        v
 ResolvedChannel(channel_id="...", ...)
```

Error classes:

- `UnknownSourceError` — source not found (includes did-you-mean if applicable).
- `AmbiguousSourceError` — partial match hits multiple sources.
- `LanguageUnavailableError` — source has no discovered channel for the language.
- `MissingLanguageError` — source has multiple languages but none was specified.
- `AmbiguousVariantError` — multiple channels match; `--variant` is required.
- `UnknownVariantError` — specified variant not found.

### `kolibri.py`

Responsibilities:

- determine `KOLIBRI_HOME`;
- run the Kolibri `importchannel` command;
- discover SQLite channel databases;
- match an imported database to a channel ID.

The Kolibri executable prefix is configurable because installations may expose either:

```text
kolibri
```

or:

```text
python -m kolibri
```

### `schema.py`

Kolibri content schemas may evolve. This module introspects SQLite tables and identifies:

- the ContentNode-like table;
- the ChannelMetadata-like table;
- the Language-like table.

Detection relies on required and optional columns rather than only a table name. Known
table names receive a higher score, but are not mandatory.

### `reader.py`

Responsibilities:

- open the source database with `mode=ro`;
- select only known metadata columns;
- normalize UUIDs stored as text or bytes;
- decode JSON metadata such as `options`;
- resolve language IDs;
- return a `Catalog` containing `CurriculumNode` objects.

No source database writes are permitted.

### `tree.py`

Responsibilities:

- order nodes by Kolibri's tree and sort fields where available;
- reconstruct paths from `parent_id`;
- calculate depth;
- detect orphan/cyclic structures defensively;
- calculate stable row hashes;
- build nested JSON trees.

The row hash includes hierarchy and metadata, allowing moved nodes to be distinguished
from ordinary metadata edits.

### `planning.py`

Creates a convenience view for learning-path construction.

It maps each non-topic metadata item to:

- subject;
- course;
- unit;
- lesson;
- item;
- about/description;
- author;
- source path and IDs.

This is intentionally heuristic. Kolibri's original tree is retained alongside the
inferred labels, and callers must use IDs and source paths when correctness matters.

### `exporters.py`

Produces atomic JSON writes:

- `manifest.json`;
- `nodes.jsonl`;
- `outline.json`;
- `catalog.json`;
- `lessons.json`.

Atomic replacement prevents readers from observing a partially written export.

### `repository.py`

Owns the local SQLite schema and query API.

It stores:

- current channels;
- current and inactive nodes;
- import snapshots;
- per-node changes.

It optionally creates an FTS5 search index. When SQLite lacks FTS5, search falls back
to `LIKE` queries.

### `agent_api.py`

Provides an allowlisted read-only facade:

- list channels;
- search;
- get node;
- list children;
- read bounded subtree;
- inspect recent changes;
- list educational sources (`sources()`);
- resolve a source by name (`source()`);
- list available languages for a source (`source_languages()`);
- resolve source + language + variant to a channel (`resolve_source()`);
- search within a source by name (`search_source()`).

It deliberately does not expose arbitrary SQL.

When a `ChannelDiscovery` backend is supplied at construction time, the source-aware
methods are enabled. Without one, they return empty results gracefully.

### `sync.py`

Orchestrates one refresh:

1. optionally run Kolibri `importchannel`;
2. locate the source channel database;
3. read and normalize the catalog;
4. write timestamped JSON files;
5. replace the `current` export;
6. synchronize SQLite and record changes.

## 4. Source model

A normalized node contains:

```text
node_id
content_id
channel_id
parent_id
kind
title
description
author
sort_order
duration_seconds
language
available
license metadata
options
curriculum metadata labels
tree_id / lft / rght
depth
path
row_hash
```

### Identifier semantics

- `node_id` identifies a node at a specific place in a channel tree.
- `content_id` may identify substantially similar content copied into multiple places.
- `(channel_id, node_id)` is the local repository primary key.

Titles are never used as identifiers.

## 5. SQLite model

### `channels`

One row per imported channel, including version and source database path.

### `nodes`

One row per source node. Important operational fields:

- `path_json` and `path_text`;
- `row_hash`;
- `is_active`;
- `first_seen_at`;
- `last_seen_at`.

Rows missing from a new source snapshot are marked inactive rather than deleted.

### `snapshots`

One row per synchronization, with aggregate counts.

### `changes`

One row per changed node:

```text
added
modified
moved
removed
```

A node is classified as `moved` when its parent or path changed. Other hash differences
are classified as `modified`.

## 6. JSON representations

### Flat source stream

`nodes.jsonl` is canonical for pipelines, diffs, and bulk processing.

### Topic outline

`outline.json` contains only `kind == "topic"` nodes and is useful for browsing the
curriculum structure.

### Full metadata tree

`catalog.json` contains all metadata nodes. It may be large but contains no resource
files.

### Planning records

`lessons.json` is denormalized for human study planning and AI input. It is not the
canonical source model because its semantic labels are inferred.

## 7. Update algorithm

For each node in the new catalog:

```text
not present previously        -> added
same row_hash                  -> unchanged
parent/path changed           -> moved
other row_hash difference     -> modified
```

Previously active nodes absent from the new catalog become inactive and produce a
`removed` change record.

The synchronization executes in one SQLite transaction. JSON snapshots are written
before the repository transaction; a failed repository write leaves a usable source
snapshot for diagnosis.

## 8. Depth strategy

There are two meanings of depth:

1. **source depth**: exact number of ancestors in the Kolibri tree;
2. **semantic depth**: subject/course/unit/lesson labels inferred for planning.

The source depth is always calculated and retained. `--max-depth` limits nested JSON
presentation only. It does not truncate SQLite or `lessons.json`.

This avoids accidentally deleting deeper metadata merely because a user wants a compact
outline.

## 9. Read and write safety

- Source Kolibri databases are opened with SQLite URI `mode=ro`.
- The project writes only beneath its configured `data` directory.
- Export files use temporary files plus atomic replacement.
- The agent facade is allowlisted and read-only.
- Arbitrary SQL execution is not part of the public API.

## 10. Compatibility and failure modes

### Channel schema changes

The schema detector scores tables by columns and known names. If no compatible node
table is found, import fails explicitly rather than guessing.

### Missing descriptions

Blank descriptions are preserved as blank. The exporter does not synthesize missing
metadata.

### Broken parent references

An orphan is treated as an additional root. This preserves the node rather than losing
it. Cycles receive a defensive `[cycle]` path marker.

### Concurrent Kolibri refresh

The safest operational order is:

1. let `importchannel` finish;
2. then read the channel database.

The orchestrator follows this order. It does not read while invoking the import command.

### FTS5 unavailable

Search falls back to normal SQLite `LIKE` matching.

## 11. Future extensions

The next milestone is a study-planning agent backed by the existing read-only query
service. Details are in `AGENTS.md`.

Later extensions may include:

- explicit prerequisite edges;
- personal mastery and progress tables;
- curriculum mappings between localized channels;
- approval workflow for AI-generated study plans;
- optional Excel exports;
- a small local web UI.
