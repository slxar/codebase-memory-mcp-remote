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
- `POST /api/artifact/<project>` accepts the raw `graph.db.zst` bytes and
  `X-CBM-Artifact-Original-Size` plus `X-CBM-Artifact-Schema-Version` headers.
  The server validates the project name, writes a metadata envelope, imports
  the artifact atomically, and invalidates its query-store cache.
- `scripts/publish-artifact.py` uploads a local artifact over HTTP(S).
- HTTPS termination is intentionally delegated to a reverse proxy or VPN;
  the native zero-dependency server does not grow a TLS dependency.

## Limits and non-goals

- Uploads are capped by the HTTP body limit (64 MiB).
- IPv4 literals are supported for binding; DNS/TLS/proxy configuration stays
  outside the binary.
- `get_code_snippet` and `search_code` still need source files at the remote
  machine's indexed repository root; graph-only uploads support structural
  graph queries.
