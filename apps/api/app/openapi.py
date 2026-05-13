"""Export the FastAPI OpenAPI spec to ``packages/shared-types/openapi.json``.

Run from the repo root::

    uv --directory apps/api run python -m app.openapi

Or with an explicit output path::

    uv --directory apps/api run python -m app.openapi /tmp/openapi.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.main import app

_DEFAULT_OUT = Path(__file__).resolve().parents[3] / "packages" / "shared-types" / "openapi.json"


def export(output_path: Path) -> Path:
    spec = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output path for the OpenAPI JSON (default: {_DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)
    written = export(args.output)
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
