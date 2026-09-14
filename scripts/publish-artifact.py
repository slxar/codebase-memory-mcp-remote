#!/usr/bin/env python3
"""Upload a locally exported codebase-memory artifact to a remote server."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="repository containing .codebase-memory")
    parser.add_argument("--url", required=True, help="remote server base URL, e.g. https://cbm.example")
    parser.add_argument("--project", help="project name (must match artifact.json project)")
    args = parser.parse_args()

    artifact_dir = args.repo / ".codebase-memory"
    artifact_path = artifact_dir / "graph.db.zst"
    metadata_path = artifact_dir / "artifact.json"
    if not artifact_path.is_file() or not metadata_path.is_file():
        print("error: expected .codebase-memory/graph.db.zst and artifact.json", file=sys.stderr)
        return 2

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: invalid artifact.json: {exc}", file=sys.stderr)
        return 2

    if not isinstance(metadata, dict):
        print("error: artifact.json must be a JSON object", file=sys.stderr)
        return 2
    project = metadata.get("project", "")
    if (not isinstance(project, str) or ".." in project or not PROJECT_RE.fullmatch(project)):
        print("error: project must be a safe name using letters, numbers, '.', '_' or '-'", file=sys.stderr)
        return 2
    if args.project is not None and args.project != project:
        print("error: --project must match artifact.json project; reindex with the desired name", file=sys.stderr)
        return 2
    schema_version = metadata.get("schema_version")
    original_size = metadata.get("original_size")
    compressed_size = metadata.get("compressed_size")
    if not isinstance(schema_version, int) or schema_version < 1:
        print("error: artifact.json has no valid schema_version", file=sys.stderr)
        return 2
    if not isinstance(original_size, int) or original_size <= 0:
        print("error: artifact.json has no valid original_size", file=sys.stderr)
        return 2
    artifact_size = artifact_path.stat().st_size
    if isinstance(compressed_size, int) and compressed_size != artifact_size:
        print("error: artifact size does not match artifact.json", file=sys.stderr)
        return 2

    base_url = args.url.rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        print("error: --url must be an HTTP(S) URL", file=sys.stderr)
        return 2
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        print("error: HTTPS is required except for localhost testing", file=sys.stderr)
        return 2

    token = os.environ.get("CBM_HTTP_TOKEN", "")
    headers = {
        "Content-Type": "application/vnd.codebase-memory.artifact",
        "Content-Length": str(artifact_size),
        "X-CBM-Artifact-Original-Size": str(original_size),
        "X-CBM-Artifact-Schema-Version": str(schema_version),
    }
    commit = metadata.get("commit")
    if isinstance(commit, str) and commit:
        headers["X-CBM-Artifact-Commit"] = commit
    if token:
        headers["Authorization"] = f"Bearer {token}"

    endpoint = f"{base_url}/api/artifact/{quote(project, safe='')}"
    request = Request(endpoint, data=artifact_path.read_bytes(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            print(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"error: remote returned HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"error: upload failed: {exc.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
