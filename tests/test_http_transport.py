#!/usr/bin/env python3
"""Local transport regression check. All test graphs/processes are cleaned up."""
import http.client
from contextlib import closing
import json
import os
from pathlib import Path
import select
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time


def main():
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else "build/c/codebase-memory-mcp").resolve()
    project = "cbm_http_transport_test"
    token = "temporary-http-transport-test"
    with tempfile.TemporaryDirectory(prefix="cbm-http-transport-") as temp:
        root = Path(temp)
        cache = root / "cache"
        cache.mkdir()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        (cache / "config.json").write_text(json.dumps({"ui_port": port}))
        env = dict(os.environ, CBM_CACHE_DIR=str(cache), TMPDIR=str(root),
                   CBM_HTTP_TOKEN=token, CBM_HTTP_HOST="127.0.0.1",
                   CBM_HTTP_ALLOWED_ORIGINS="https://review.example")

        def request(method, path, body=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            fields = {"Authorization": "Bearer " + token,
                      "Accept": "application/json, text/event-stream",
                      "Content-Type": "application/json",
                      "MCP-Protocol-Version": "2025-06-18"}
            fields.update(headers or {})
            try:
                conn.request(method, path, body=body, headers=fields)
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()

        def rpc(method, params=None):
            status, data = request("POST", "/mcp", json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}))
            assert status == 200, (status, data)
            return json.loads(data)

        def ping_ms():
            start = time.perf_counter()
            assert rpc("ping")["result"] == {}
            return (time.perf_counter() - start) * 1000

        def raw_query(sock, query):
            data = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "query_graph", "arguments": {
                                   "project": project, "query": query, "max_rows": 10000}}}).encode()
            sock.sendall((f"POST /mcp HTTP/1.1\r\nHost: localhost\r\n"
                          f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"
                          f"MCP-Protocol-Version: 2025-06-18\r\n"
                          f"Content-Length: {len(data)}\r\n\r\n").encode() + data)

        with (root / "server.log").open("w") as log:
            repo = root / "repo"
            repo.mkdir()
            (repo / "demo.py").write_text("def transport_test():\n    return 42\n")
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "demo.py"], check=True)
            index_request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "index_repository", "arguments": {
                    "repo_path": str(repo), "name": project, "mode": "fast"}}}
            indexed = subprocess.run([str(binary)], input=json.dumps(index_request) + "\n",
                                     text=True, stdout=subprocess.PIPE, stderr=log,
                                     cwd=root, env=env, check=True, timeout=30)
            assert not json.loads(indexed.stdout)["result"]["isError"], indexed.stdout
            # Seed before HTTP startup so its cached SQLite snapshot includes the test rows.
            with closing(sqlite3.connect(cache / (project + ".db"))) as db, db:
                db.executemany("INSERT INTO nodes(project,label,name,qualified_name) VALUES(?,?,?,?)",
                               [(project, "Function", "x" * 2048, "temporary_" + str(i))
                                for i in range(9000)])
            proc = subprocess.Popen([str(binary), "--transport=streamable-http"],
                                    cwd=root, env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        request("GET", "/probe")
                        break
                    except OSError:
                        assert proc.poll() is None, "server exited during startup"
                        time.sleep(.05)
                baseline = [ping_ms() for _ in range(7)]
                delayed = []
                for _ in range(3):
                    with socket.create_connection(("127.0.0.1", port)) as slow:
                        slow.sendall(("POST /api/artifact/cbm_http_transport_test HTTP/1.1\r\n"
                                      f"Authorization: Bearer {token}\r\n"
                                      "Content-Length: 67108864\r\n\r\nx").encode())
                        time.sleep(.05)
                        delayed.append(ping_ms())
                assert max(delayed) < 1000, delayed

                notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
                assert request("POST", "/mcp", notification) == (202, b"")
                assert request("GET", "/mcp")[0] == 405
                assert request("POST", "/mcp", "{}", {"MCP-Protocol-Version": "invalid"})[0] == 400
                assert request("POST", "/mcp", "{}", {"Origin": "https://untrusted.example"})[0] == 403
                assert request("OPTIONS", "/mcp", headers={"Origin": "https://review.example"})[0] == 204

                with socket.socket() as slow:
                    slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                    slow.connect(("127.0.0.1", port))
                    raw_query(slow, "MATCH (n) RETURN n.name LIMIT 10000")
                    assert select.select([slow], [], [], 10)[0], "large response never started"
                    unread_ping = ping_ms()
                    assert unread_ping < 1000, unread_ping
                    time.sleep(5.3)
                    slow.settimeout(3)
                    data = bytearray()
                    while True:
                        chunk = slow.recv(65536)
                        if not chunk:
                            break
                        data.extend(chunk)
                    head, body = bytes(data).split(b"\r\n\r\n", 1)
                    length = next(int(line.split(b":", 1)[1]) for line in head.split(b"\r\n")
                                  if line.lower().startswith(b"content-length:"))
                    assert length > 8 * 1024 * 1024, (length, body[:2048].decode(errors="replace"))
                    assert len(body) < length, "stalled response did not hit its write deadline"

                with socket.create_connection(("127.0.0.1", port)) as slow:
                    slow.sendall(b"GET /partial")
                    time.sleep(.05)
                    proc.terminate()
                    proc.wait(timeout=8)
                assert proc.returncode == 0, proc.returncode
                print(json.dumps({"baseline_median_ms": statistics.median(baseline),
                                  "ping_during_slow_upload_median_ms": statistics.median(delayed),
                                  "ping_during_unread_response_ms": unread_ping,
                                  "write_deadline": "passed", "slow_peer_shutdown": "passed"}, indent=2))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
    print("All temporary test graphs, files, and server processes were removed.")


if __name__ == "__main__":
    main()
