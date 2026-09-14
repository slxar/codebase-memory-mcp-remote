#!/usr/bin/env python3
"""Publisher validation must reject aliases before attempting an upload."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch


def main():
    path = Path(__file__).resolve().parents[1] / "scripts" / "publish-artifact.py"
    spec = importlib.util.spec_from_file_location("publish_artifact", path)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    with tempfile.TemporaryDirectory(prefix="cbm_test_publisher_") as tmp:
        artifacts = Path(tmp) / ".codebase-memory"
        artifacts.mkdir()
        (artifacts / "graph.db.zst").write_bytes(b"fixture")
        metadata = {"project": "test-proj", "schema_version": 1, "original_size": 100,
                    "compressed_size": 7}
        metadata_path = artifacts / "artifact.json"
        argv = [str(path), tmp, "--url", "http://127.0.0.1", "--project", "alias"]
        for value in (metadata, [], {**metadata, "project": None}):
            metadata_path.write_text(json.dumps(value), encoding="utf-8")
            with patch("sys.argv", argv), patch.object(publisher, "urlopen") as upload:
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    assert publisher.main() == 2
                upload.assert_not_called()

        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        for override in ([], ["--project", "test-proj"]):
            with patch("sys.argv", argv[:-2] + override), patch.object(publisher, "urlopen") as upload:
                upload.return_value.__enter__.return_value.read.return_value = b'{"status":"imported"}'
                with contextlib.redirect_stdout(io.StringIO()):
                    assert publisher.main() == 0
                assert upload.call_args.args[0].full_url.endswith("/api/artifact/test-proj")
    print("publisher validation passed")


if __name__ == "__main__":
    main()
