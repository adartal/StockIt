"""OpenAPI export smoke test for M6."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.openapi import export


def test_openapi_export_writes_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "openapi.json"
        written = export(out)
        assert written == out
        spec = json.loads(out.read_text())
        assert spec["info"]["title"] == "StockIt API"
        paths = spec["paths"]
        assert "/plans" in paths
        assert "/watchlist" in paths
        assert "/plans/{plan_id}/notes" in paths
