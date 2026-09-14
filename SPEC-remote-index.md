# Remote artifact indexing

## Goal

Index source code on one machine, publish the existing `.codebase-memory`
artifact to a shared server, and query that server from other machines over
streamable HTTP.

## Contract

- `--transport=streamable-http` continues to bind `127.0.0.1` by default.
- `CBM_HTTP_HOST` or `--host=<IPv4>` selects the bind address.
- A non-loopback bind is refused unless `CBM_HTTP_TOKEN` is set.
- When a token is configured, every non-`OPTIONS` HTTP request must include
  `Authorization: Bearer <token>`.
- Authentication, Origin, protocol-version, and body-size checks run after
  headers are parsed and before a request body is allocated or received.
- Browser origins default to HTTP(S) localhost/127.0.0.1 with a valid optional
  port. `CBM_HTTP_ALLOWED_ORIGINS` adds exact comma-separated origins for remote
  browser clients; disallowed origins are rejected, including preflights.
- `/mcp` accepts supported `MCP-Protocol-Version` values, returns 202 for
  notifications and 405 for unsupported methods (including GET without SSE).
- `POST /api/artifact/<project>` accepts the raw `graph.db.zst` bytes and
  `X-CBM-Artifact-Original-Size` plus `X-CBM-Artifact-Schema-Version` headers.
  The server validates the staged SQLite graph, schema, referential integrity,
  and single matching project before replacing the query database. A rejected
  artifact leaves the previous graph usable.
- `scripts/publish-artifact.py` uploads a local artifact over HTTP(S). Its
  optional `--project` must match the embedded name; use `index_repository`'s
  `name` option to choose a name before exporting.
- HTTPS termination is intentionally delegated to a reverse proxy or VPN;
  the native zero-dependency server does not grow a TLS dependency.

## Limits and non-goals

- Artifact uploads are capped at 64 MiB compressed and 1 GiB decompressed.
  Other request bodies are capped at 1 MiB.
- Four workers handle socket I/O, with five-second read and write deadlines.
  Graph execution remains serialized; responses are copied before releasing
  its lock and sent outside that lock. Four stalled peers can occupy all four
  workers until their deadlines; this is bounded capacity, not load isolation.
- Idle cached query stores are evicted after 60 seconds.
- Imports still buffer the compressed and decompressed artifact. Streaming
  decompression is deferred pending memory measurements on representative graphs.
- IPv4 literals are supported for binding; DNS/TLS/proxy configuration stays
  outside the binary.
- `get_code_snippet` and `search_code` still need source files at the remote
  machine's indexed repository root; graph-only uploads support structural
  graph queries.

## Verification

`make -f Makefile.cbm test-remote` runs HTTP/artifact regressions, publisher
validation, and local multi-client checks. Its temporary graph data and server
processes are removed automatically. `make -f Makefile.cbm test` runs the full
C suite with address and undefined-behavior sanitizers.
