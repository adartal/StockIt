"""Structured diff between two `Plan` snapshots.

Used by the watchlist scheduler (and the on-demand refresh route) to record
a `PlanRevision.diff_json` payload that the frontend can render as a "what
changed since the last plan" panel.

The diff is intentionally shallow: top-level Plan fields and a couple of
domain-aware sub-diffs (catalysts as a set-by-(date,description), risk
flags as a set-by-(code,severity), a stop-violation alert). The goal is a
small JSON blob that highlights the changes a reader cares about, not a
line-by-line dump of every nested field — readers can always re-render
the full new payload if they want detail.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.pipeline.schema import Catalyst, Plan, RiskFlag

# Fields we surface as plain before/after diffs when they change.
_SIMPLE_FIELDS: tuple[str, ...] = (
    "thesis",
    "conviction",
    "review_cadence",
)

# Fields we serialize as nested dicts before/after when they change.
_STRUCT_FIELDS: tuple[str, ...] = (
    "entry",
    "stop",
    "sizing",
    "exits",
)


def _dump(value: Any) -> Any:
    """JSON-safe serialization for a Plan field value."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


def _catalyst_key(c: Catalyst) -> tuple[str, str, str]:
    return (c.date.isoformat(), c.description, c.kind)


def _risk_flag_key(f: RiskFlag) -> tuple[str, str, str]:
    return (f.severity, f.code, f.message)


def _diff_catalysts(
    old: list[Catalyst], new: list[Catalyst]
) -> dict[str, list[dict[str, Any]]]:
    old_by_key = {_catalyst_key(c): c for c in old}
    new_by_key = {_catalyst_key(c): c for c in new}
    added_keys = new_by_key.keys() - old_by_key.keys()
    removed_keys = old_by_key.keys() - new_by_key.keys()
    return {
        "added": [new_by_key[k].model_dump(mode="json") for k in sorted(added_keys)],
        "removed": [
            old_by_key[k].model_dump(mode="json") for k in sorted(removed_keys)
        ],
    }


def _diff_risk_flags(
    old: list[RiskFlag], new: list[RiskFlag]
) -> dict[str, list[dict[str, Any]]]:
    old_by_key = {_risk_flag_key(f): f for f in old}
    new_by_key = {_risk_flag_key(f): f for f in new}
    added_keys = new_by_key.keys() - old_by_key.keys()
    removed_keys = old_by_key.keys() - new_by_key.keys()
    return {
        "added": [new_by_key[k].model_dump(mode="json") for k in sorted(added_keys)],
        "removed": [
            old_by_key[k].model_dump(mode="json") for k in sorted(removed_keys)
        ],
    }


def _stop_alert(old: Plan, new: Plan) -> str | None:
    """Surface stop-related problems worth alerting on.

    Triggers when the new plan's stop is structurally invalid (>= the
    first entry level) or has been loosened relative to the old plan
    (raised on a long). Both are conditions a reviewer should see at a
    glance rather than discover by scrolling through the new payload.
    """
    new_stop = Decimal(str(new.stop.price))
    new_entry_first = Decimal(str(new.entry.levels[0]))
    if new_stop >= new_entry_first:
        return (
            f"new stop {new_stop} is not below first entry {new_entry_first} "
            "(long-only assumption)"
        )
    old_stop = Decimal(str(old.stop.price))
    if new_stop > old_stop:
        return f"stop loosened from {old_stop} to {new_stop}"
    return None


def diff_plans(old: Plan, new: Plan) -> dict[str, Any]:
    """Return a structured diff between two Plan snapshots.

    Shape::

        {
          "ticker": str,
          "changed_fields": list[str],
          "thesis":         {"before": str, "after": str} | absent,
          "conviction":     {"before": str, "after": str} | absent,
          "review_cadence": {"before": str, "after": str} | absent,
          "entry":          {"before": dict, "after": dict} | absent,
          "stop":           {"before": dict, "after": dict} | absent,
          "sizing":         {"before": dict, "after": dict} | absent,
          "exits":          {"before": list, "after": list} | absent,
          "catalysts":      {"added": [...], "removed": [...]},
          "risk_flags":     {"added": [...], "removed": [...]},
          "stop_alert":     str | None,
        }

    Fields that didn't change are *omitted* (not emitted as ``None``) so
    the JSON blob stays compact. ``changed_fields`` lists every top-level
    Plan field whose value differs, which lets a frontend cheaply check
    "anything to show?" without inspecting each branch.
    """
    diff: dict[str, Any] = {"ticker": new.ticker}
    changed: list[str] = []

    for name in _SIMPLE_FIELDS:
        old_val = getattr(old, name)
        new_val = getattr(new, name)
        if old_val != new_val:
            diff[name] = {"before": old_val, "after": new_val}
            changed.append(name)

    for name in _STRUCT_FIELDS:
        old_val = getattr(old, name)
        new_val = getattr(new, name)
        old_dump = _dump(old_val)
        new_dump = _dump(new_val)
        if old_dump != new_dump:
            diff[name] = {"before": old_dump, "after": new_dump}
            changed.append(name)

    catalyst_diff = _diff_catalysts(old.catalysts, new.catalysts)
    diff["catalysts"] = catalyst_diff
    if catalyst_diff["added"] or catalyst_diff["removed"]:
        changed.append("catalysts")

    risk_flag_diff = _diff_risk_flags(old.risk_flags, new.risk_flags)
    diff["risk_flags"] = risk_flag_diff
    if risk_flag_diff["added"] or risk_flag_diff["removed"]:
        changed.append("risk_flags")

    diff["stop_alert"] = _stop_alert(old, new)
    diff["changed_fields"] = changed
    return diff


__all__ = ["diff_plans"]
