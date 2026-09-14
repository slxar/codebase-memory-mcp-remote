- [x] Bind and auth tests (RED)
- [x] Implement bind and auth (GREEN)
- [x] Artifact upload/import endpoint
- [x] Publisher helper and README usage
- [x] Full verification and GitHub push

## Review fixes (2026-09-05)

- [x] Reject malformed/mismatched artifacts while preserving existing queries.
- [x] Reject publisher project aliases before upload.
- [x] Authenticate and validate MCP headers before receiving bodies.
- [x] Bound socket I/O with four workers and read/write deadlines; serialize graph work.
- [x] Reuse idle-store eviction and avoid reformatting serialized RPC responses.
- [x] Complete full sanitizer and multi-client regression checks.
- [x] Record verified results and remaining limits in project memory.
