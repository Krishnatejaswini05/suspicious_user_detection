# ADR 005: Parquet for data, DuckDB for queries, behind storage interfaces

Status: accepted

## Context

v1 runs locally. Feature computation is analytical: counts and windows over millions of
events. We want no servers to operate and no lock-in.

## Decision

- Data is stored as **Parquet** files, partitioned by platform and date.
- **DuckDB** (an embedded analytical database, no server) queries those files with SQL.
- All access goes through interfaces in `storage/`; no other package imports DuckDB.
- Point-in-time reads ("events up to time *t*") are part of the event store interface.

## Alternatives

- PostgreSQL: better for many concurrent writers; needs a server. Can be added as
  another backend.
- SQLite: good for row lookups, slower for analytical queries.

## Consequences

- Zero setup, fast analytics on a laptop, portable data format.
- Single-process writes; a server database becomes necessary only at larger scale,
  and only `storage/` would change.

## Update: Parquet I/O through DuckDB only (no PyArrow)

An application-control policy on the development machine began blocking PyArrow's
native library. All Parquet reading and writing now goes through
`storage/parquet.py`, which uses DuckDB alone:

- Rows are staged as JSON lines and converted by DuckDB `COPY ... TO ... (FORMAT parquet)`.
- The event store writes every `platform=/date=` folder in one `PARTITION_BY` write.
- Timezone-aware timestamps cross the Python/DuckDB boundary as epoch microseconds
  (direct conversion would need `pytz`); on disk they are standard UTC timestamps.
- Large ID lists are staged as a file and joined, not passed as query parameters,
  which is much faster.

PyArrow is no longer a dependency. Files on disk are unchanged in layout and readable
by any Parquet tool.
