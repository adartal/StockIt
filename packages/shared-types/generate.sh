#!/usr/bin/env bash
#
# Generate TypeScript types for the frontend from the API's pydantic v2 models.
#
# Source of truth: apps/api/app/pipeline/schema.py
# Output:         apps/web/src/types/generated.ts
#
# Re-run after editing schema.py. Commit the generated file alongside the
# schema change so reviewers can see the wire-shape diff in one PR.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

SCHEMA="$REPO_ROOT/apps/api/app/pipeline/schema.py"
OUT="$REPO_ROOT/apps/web/src/types/generated.ts"

if [[ ! -f "$SCHEMA" ]]; then
  echo "schema not found: $SCHEMA" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"

cd "$REPO_ROOT/apps/api"
PYTHONPATH="$REPO_ROOT/apps/api" uv run python "$HERE/_emit_ts.py" > "$OUT"

echo "wrote $OUT"
