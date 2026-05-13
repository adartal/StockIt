# shared-types

TypeScript types generated from the API's pydantic v2 models in
[`apps/api/app/pipeline/schema.py`](../../apps/api/app/pipeline/schema.py).

The generated output lives at
[`apps/web/src/types/generated.ts`](../../apps/web/src/types/generated.ts)
and is committed so the frontend builds without running the generator.

## Re-run when

- You added, removed, or renamed a field in any model under `pipeline/schema.py`.
- You changed a literal/enum value, a default, or an optionality.
- You added a new pydantic model that the frontend should consume — also
  add it to the `MODELS` list in `_emit_ts.py`.

## Don't re-run for

- Internal refactors that don't change the JSON shape (renames of private
  helpers, docstring edits, etc.).

## How

```bash
bash packages/shared-types/generate.sh
```

The script:
1. Imports `app.pipeline.schema` from the API venv (`uv run`).
2. Calls `pydantic.json_schema.models_json_schema(..., mode="serialization")`
   so the wire shape — including `Decimal` → `string` — is what we emit.
3. Walks `$defs` and writes one `export interface` per model (and string
   union aliases for top-level enums) to `apps/web/src/types/generated.ts`.

Output is deterministic (sorted by definition name) so diffs stay tight.

## Why a custom emitter

`datamodel-code-generator` only emits Python types. `pydantic-to-typescript`
shells out to the npm `json-schema-to-typescript`, which adds a Node toolchain
dependency for ~200 lines of work. The Python emitter in
[`_emit_ts.py`](./_emit_ts.py) covers exactly the JSON Schema subset that
`schema.py` produces; extend it if you introduce new constructs (tuples,
discriminated unions, etc.).
