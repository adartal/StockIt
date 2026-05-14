"""Unit tests for `app.pipeline.diff.diff_plans` (M9)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.pipeline.diff import diff_plans
from app.pipeline.schema import (
    Catalyst,
    Citation,
    Entry,
    ExitLevel,
    Plan,
    RiskFlag,
    Sizing,
    Stop,
)


def _base_plan() -> Plan:
    return Plan(
        ticker="AAPL",
        horizon="swing",
        capital=Decimal("10000"),
        generated_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        thesis="initial thesis",
        conviction="medium",
        entry=Entry(kind="limit", levels=[Decimal("100")], conditions="on dip"),
        sizing=Sizing(
            risk_pct=1.0,
            shares=20,
            dollar_exposure=Decimal("2000"),
            R_value=Decimal("5"),
        ),
        stop=Stop(price=Decimal("95"), kind="technical", rationale="below swing low"),
        exits=[
            ExitLevel(
                kind="scale_out",
                price=Decimal("110"),
                trigger="resistance",
                portion=0.5,
            )
        ],
        catalysts=[],
        risk_flags=[],
        review_cadence="weekly",
        sources=[
            Citation(
                url="https://example.com/a",
                title="t",
                source="src",
                fetched_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )
        ],
    )


def test_diff_identical_plans_has_no_changed_fields() -> None:
    plan = _base_plan()
    diff = diff_plans(plan, plan)
    assert diff["changed_fields"] == []
    assert diff["catalysts"] == {"added": [], "removed": []}
    assert diff["risk_flags"] == {"added": [], "removed": []}
    assert diff["stop_alert"] is None
    assert diff["ticker"] == "AAPL"


def test_thesis_change_surfaces_before_after() -> None:
    old = _base_plan()
    new = old.model_copy(update={"thesis": "revised thesis"})
    diff = diff_plans(old, new)
    assert diff["thesis"] == {"before": "initial thesis", "after": "revised thesis"}
    assert "thesis" in diff["changed_fields"]


def test_conviction_and_review_cadence_changes() -> None:
    old = _base_plan()
    new = old.model_copy(update={"conviction": "high", "review_cadence": "daily"})
    diff = diff_plans(old, new)
    assert diff["conviction"] == {"before": "medium", "after": "high"}
    assert diff["review_cadence"] == {"before": "weekly", "after": "daily"}
    assert set(diff["changed_fields"]) >= {"conviction", "review_cadence"}


def test_added_and_removed_catalysts() -> None:
    old = _base_plan().model_copy(
        update={
            "catalysts": [
                Catalyst(
                    date=date(2026, 6, 1),
                    description="earnings",
                    kind="earnings",
                )
            ]
        }
    )
    new = _base_plan().model_copy(
        update={
            "catalysts": [
                Catalyst(
                    date=date(2026, 7, 1),
                    description="fomc",
                    kind="macro",
                )
            ]
        }
    )
    diff = diff_plans(old, new)
    assert "catalysts" in diff["changed_fields"]
    added = diff["catalysts"]["added"]
    removed = diff["catalysts"]["removed"]
    assert len(added) == 1 and added[0]["description"] == "fomc"
    assert len(removed) == 1 and removed[0]["description"] == "earnings"


def test_stop_loosened_emits_alert() -> None:
    old = _base_plan()
    new = old.model_copy(
        update={
            "stop": Stop(
                price=Decimal("97"),
                kind="technical",
                rationale="raised after consolidation",
            )
        }
    )
    diff = diff_plans(old, new)
    assert diff["stop_alert"] is not None
    assert "loosened" in diff["stop_alert"]
    assert "stop" in diff["changed_fields"]


def test_invalid_stop_above_entry_emits_alert() -> None:
    old = _base_plan()
    new = old.model_copy(
        update={
            "stop": Stop(
                price=Decimal("105"),
                kind="technical",
                rationale="broken",
            )
        }
    )
    diff = diff_plans(old, new)
    assert diff["stop_alert"] is not None
    assert "not below" in diff["stop_alert"]


def test_stop_tightened_no_alert() -> None:
    old = _base_plan()
    new = old.model_copy(
        update={
            "stop": Stop(
                price=Decimal("93"),
                kind="technical",
                rationale="tightened",
            )
        }
    )
    diff = diff_plans(old, new)
    assert diff["stop_alert"] is None
    assert "stop" in diff["changed_fields"]


def test_risk_flags_added_and_removed() -> None:
    old = _base_plan().model_copy(
        update={
            "risk_flags": [
                RiskFlag(severity="warn", code="sector_concentration", message="old"),
            ]
        }
    )
    new = _base_plan().model_copy(
        update={
            "risk_flags": [
                RiskFlag(severity="warn", code="position_cap", message="new"),
            ]
        }
    )
    diff = diff_plans(old, new)
    assert "risk_flags" in diff["changed_fields"]
    assert [f["code"] for f in diff["risk_flags"]["added"]] == ["position_cap"]
    assert [f["code"] for f in diff["risk_flags"]["removed"]] == ["sector_concentration"]


def test_entry_change_serializes_as_dict_pair() -> None:
    old = _base_plan()
    new = old.model_copy(
        update={
            "entry": Entry(
                kind="limit", levels=[Decimal("102")], conditions="break out"
            )
        }
    )
    diff = diff_plans(old, new)
    assert "entry" in diff["changed_fields"]
    assert diff["entry"]["before"]["levels"] == ["100"]
    assert diff["entry"]["after"]["levels"] == ["102"]
