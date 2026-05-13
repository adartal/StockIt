"""Emit TypeScript type definitions from the StockIt pydantic schemas.

Walks the serialization-mode JSON Schema produced by pydantic v2 and writes
one TS interface per `$defs` entry, plus union/string-literal aliases for the
horizon/conviction/etc enums. Output is deterministic so diffs stay small.

This intentionally supports only the JSON Schema subset that
`apps/api/app/pipeline/schema.py` emits — keep this in sync if you add new
JSON Schema constructs (e.g. tuples, discriminated unions) to schema.py.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from pydantic.json_schema import models_json_schema

from app.pipeline import schema as s

MODELS = [
    s.Citation,
    s.Entry,
    s.Sizing,
    s.Stop,
    s.ExitLevel,
    s.Catalyst,
    s.RiskFlag,
    s.Plan,
    s.AnalystOutput,
]


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _ts_type(node: dict[str, Any]) -> str:
    if "$ref" in node:
        return _ref_name(node["$ref"])
    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])
    if "const" in node:
        return json.dumps(node["const"])
    if "anyOf" in node:
        return " | ".join(_ts_type(sub) for sub in node["anyOf"])
    t = node.get("type")
    if t == "array":
        items = node.get("items", {})
        return f"({_ts_type(items)})[]"
    if t == "object":
        ap = node.get("additionalProperties")
        if isinstance(ap, dict):
            return f"Record<string, {_ts_type(ap)}>"
        return "Record<string, unknown>"
    if t == "string":
        if node.get("format") in {"date", "date-time"}:
            return "string"
        return "string"
    if t in {"integer", "number"}:
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if isinstance(t, list):
        return " | ".join(_ts_type({"type": x}) for x in t)
    return "unknown"


_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _prop_key(name: str) -> str:
    return name if _IDENT.match(name) else json.dumps(name)


def _emit_interface(name: str, node: dict[str, Any]) -> str:
    required = set(node.get("required", []))
    props = node.get("properties", {})
    lines = [f"export interface {name} {{"]
    for prop_name, prop_node in props.items():
        optional = "" if prop_name in required else "?"
        ts = _ts_type(prop_node)
        lines.append(f"  {_prop_key(prop_name)}{optional}: {ts};")
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    _, top = models_json_schema(
        [(m, "serialization") for m in MODELS],
        title="StockItSchemas",
    )
    defs: dict[str, Any] = top.get("$defs", {})
    out: list[str] = [
        "/* eslint-disable */",
        "/**",
        " * AUTO-GENERATED. Do not edit by hand.",
        " * Run `packages/shared-types/generate.sh` after changing",
        " * `apps/api/app/pipeline/schema.py`.",
        " */",
        "",
    ]
    for name in sorted(defs.keys()):
        node = defs[name]
        if node.get("type") == "object" or "properties" in node:
            out.append(_emit_interface(name, node))
            out.append("")
        elif "enum" in node:
            out.append(f"export type {name} = {_ts_type(node)};")
            out.append("")
    sys.stdout.write("\n".join(out).rstrip() + "\n")


if __name__ == "__main__":
    main()
