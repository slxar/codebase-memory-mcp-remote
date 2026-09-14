/*
 * httpd.h — First-party HTTP/1.1 server transport for the graph UI.
 *
 * Original implementation written for this project from RFC 9112 and the
 * needs of the graph-UI endpoints and authenticated remote MCP.
 *
 * Design constraints (deliberate — do not "improve" without reading this):
 *   - Socket I/O may run concurrently; each connection has one owner. The
 *     routing layer serializes graph operations and defers replies until
 *     after unlocking, so a stalled peer cannot hold the graph lock.
 *   - Binds an explicit IPv4 address. cbm_httpd_listen() remains loopback-only.
 *   - Every response carries explicit Content-Length and "Connection: close";
 *     keep-alive is intentionally NOT implemented (smaller parsing surface;
 *     loopback reconnects are sub-millisecond). Known trade-off: on Windows,
 *     aggressive UI polling accumulates TIME_WAIT sockets against the ~16K
 *     dynamic-port ceiling — revisit only if real users report it.
 *   - Strict parsing: CRLF line endings only (bare LF rejected), request
 *     head capped at 16 KB (real requests here are < 1 KB; the cap exists
 *     to bound memory, not to accommodate growth), bodies read only via
 *     Content-Length (capped), Transfer-Encoding: chunked rejected with 411.
 *   - The request path is matched RAW — never percent-decoded before
 *     routing ("/api%2Fbrowse" must not match "/api/browse"). "%00" or a
 *     raw NUL anywhere in the request target is rejected with 400. Only
 *     query parameter VALUES are decoded (cbm_http_query_param), and
 *     decoded values containing NUL are rejected.
 */
#ifndef CBM_UI_HTTPD_H
#define CBM_UI_HTTPD_H

#include <stdbool.h>
#include <stddef.h>

/* Maximum request head (request line + headers + terminating CRLFCRLF). */
#define CBM_HTTP_MAX_HEAD (16 * 1024)
/* Maximum request body accepted via Content-Length (RPC and artifact upload). */
#define CBM_HTTP_MAX_BODY (64 * 1024 * 1024)
/* Default per-connection receive deadline. */
#define CBM_HTTP_RECV_DEADLINE_MS 5000
#define CBM_HTTP_SEND_DEADLINE_MS 5000

typedef struct cbm_httpd cbm_httpd_t;         /* listener */
typedef struct cbm_http_conn cbm_http_conn_t; /* accepted connection */

/* A parsed request. `path` and `query` are raw (NOT percent-decoded).
 * `origin`, `accept_language`, and authentication/artifact headers are the
 * values consumed by the routing layer ("" when absent). `body` is
 * heap-allocated, NUL-terminated. */
typedef struct {
    char method[16];
    char path[2048];
    char query[2048];
    char origin[256];
    char accept_language[256];
    char authorization[256];
    char protocol_version[32];
    char artifact_original_size[64];
    char artifact_schema_version[32];
    char artifact_commit[128];
    char *body;
    size_t body_len;
} cbm_http_req_t;

/* ── Listener lifecycle ───────────────────────────────────────── */

/* Listen on 127.0.0.1:<port>. port 0 binds an ephemeral port (tests).
 * Returns NULL if the port is unavailable. */
cbm_httpd_t *cbm_httpd_listen(int port);

/* Listen on an IPv4 literal. Returns NULL for invalid addresses or bind
 * failures. The caller enforces any policy about which addresses are allowed. */
cbm_httpd_t *cbm_httpd_listen_on(int port, const char *bind_address);

/* The actually-bound port (differs from the requested one for port 0). */
int cbm_httpd_port(const cbm_httpd_t *d);

/* Override the per-connection receive deadline (tests use short values). */
void cbm_httpd_set_recv_deadline_ms(cbm_httpd_t *d, int ms);
void cbm_httpd_set_send_deadline_ms(cbm_httpd_t *d, int ms);

void cbm_httpd_close(cbm_httpd_t *d);

/* ── Connection handling ──────────────────────────────────────── */

/* Wait up to timeout_ms for a client. NULL on timeout (caller re-checks
 * its stop flag and calls again). */
cbm_http_conn_t *cbm_httpd_accept(cbm_httpd_t *d, int timeout_ms);

/* Read and parse one request from the connection.
 * Returns 0 on success. On failure returns the HTTP status the caller
 * should send before closing (400, 408, 411, 413, 431), or -1 for a
 * connection-level error where no response is possible. */
int cbm_httpd_read_request(cbm_http_conn_t *c, cbm_http_req_t *req);

/* Validate parsed headers before allocating or receiving the body. The check
 * returns zero to continue, or an HTTP error status to reject the request. */
typedef int (*cbm_http_head_check_fn)(const cbm_http_req_t *req, size_t content_length, void *ctx);
int cbm_httpd_read_request_checked(cbm_http_conn_t *c, cbm_http_req_t *req,
                                  cbm_http_head_check_fn check, void *ctx);

void cbm_http_req_free(cbm_http_req_t *req);

/* Copy replies into the connection until flush, so dispatch can release its
 * graph lock before socket writes. The connection owns and frees the copy. */
void cbm_http_conn_defer_response(cbm_http_conn_t *c);
void cbm_httpd_flush_response(cbm_http_conn_t *c);

/* Send a response. extra_headers is a string of zero or more complete
 * "Name: value\r\n" lines (may be ""). Content-Length and
 * "Connection: close" are always added here — callers must not. */
void cbm_http_replyf(cbm_http_conn_t *c, int status, const char *extra_headers, const char *fmt,
                     ...)
#if defined(__GNUC__) || defined(__clang__)
    __attribute__((format(printf, 4, 5)))
#endif
    ;

/* Binary-safe variant for embedded assets. */
void cbm_http_reply_buf(cbm_http_conn_t *c, int status, const char *extra_headers, const void *data,
                        size_t len);

int cbm_http_conn_status(const cbm_http_conn_t *c);
size_t cbm_http_conn_response_bytes(const cbm_http_conn_t *c);
void cbm_httpd_conn_close(cbm_http_conn_t *c);

/* ── Pure helpers (unit-tested without sockets) ───────────────── */

/* Parse a request head from `data` (which may also contain body bytes).
 * On success returns 0 and sets *body_offset (start of body within data)
 * and *content_length (0 when no Content-Length header is present).
 * Returns CBM_HTTP_NEED_MORE when the terminating CRLFCRLF has not
 * arrived yet, otherwise the HTTP error status to send (400/411/413/431).
 * req->body / req->body_len are NOT touched here. */
#define CBM_HTTP_NEED_MORE (-1)
int cbm_http_parse_head(const char *data, size_t len, cbm_http_req_t *req, size_t *body_offset,
                        size_t *content_length);

/* Exact match, or prefix match when `pattern` ends with '*'.
 * Used for both route patterns ("/api/layout*", "/assets" + star) and the
 * CORS origin allow-list ("http://localhost:*", "http://127.0.0.1:*"). */
bool cbm_http_path_match(const char *str, const char *pattern);

/* Extract a query parameter value, percent-decoded (%XX and '+' → space).
 * Returns true only for a present, non-empty value that fits buf and
 * contains no NUL after decoding. */
bool cbm_http_query_param(const char *query, const char *name, char *buf, int bufsz);

#endif /* CBM_UI_HTTPD_H */
