"""Plan ↔ JSON round-trip integrity test.

This locks the wire shape: any change that breaks `Plan -> JSON -> Plan`
equality will be caught here before downstream code drifts.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from app.pipeline.schema import (
    AnalystOutput,
    Catalyst,
    Citation,
    Entry,
    ExitLevel,
    Plan,
    RiskFlag,
    Sizing,
    Stop,
)


def _sample_plan() -> Plan:
    fetched = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    return Plan(
        ticker="AAPL",
        horizon="swing",
        capital=Decimal("10000.00"),
        generated_at=datetime(2026, 5, 13, 14, 30, tzinfo=UTC),
        thesis="iPhone 17 cycle + services margin expansion.",
        conviction="medium",
        entry=Entry(
            kind="limit",
            levels=[Decimal("185.50"), Decimal("182.00")],
            conditions="Scale in on pullback to 50DMA.",
        ),
        sizing=Sizing(
            risk_pct=1.0,
            shares=20,
            dollar_exposure=Decimal("3710.00"),
            R_value=Decimal("5.00"),
        ),
        stop=Stop(
            price=Decimal("180.50"),
            kind="technical",
            rationale="Below 50DMA and prior swing low.",
        ),
        exits=[
            ExitLevel(
                kind="scale_out",
                price=Decimal("200.00"),
                trigger="At 200 resistance",
                portion=0.5,
            ),
            ExitLevel(
                kind="invalidation",
                price=None,
                trigger="Earnings miss + guide-down",
                portion=None,
            ),
        ],
        catalysts=[
            Catalyst(date=date(2026, 7, 25), description="Q3 earnings", kind="earnings"),
        ],
        risk_flags=[
            RiskFlag(severity="info", code="MEGA_CAP_BETA", message="High correlation with QQQ."),
        ],
        review_cadence="weekly until earnings",
        sources=[
            Citation(
                url="https://example.com/aapl-10q",
                title="AAPL 10-Q Q2 2026",
                source="edgar",
                fetched_at=fetched,
            )
        ],
    )


def test_plan_roundtrip_equality() -> None:
    plan = _sample_plan()
    payload = plan.model_dump_json()
    restored = Plan.model_validate_json(payload)
    assert restored == plan


def test_plan_decimal_serialized_as_string() -> None:
    plan = _sample_plan()
    raw = json.loads(plan.model_dump_json())
    assert raw["capital"] == "10000.00"
    assert raw["entry"]["levels"] == ["185.50", "182.00"]
    assert raw["stop"]["price"] == "180.50"
    assert raw["sizing"]["dollar_exposure"] == "3710.00"
    assert raw["sizing"]["R_value"] == "5.00"


def test_analyst_output_roundtrip() -> None:
    ao = AnalystOutput(
        findings=["Gross margin up 80bps YoY.", "Services 24% of revenue."],
        confidence=0.72,
        key_metrics={"gross_margin": 0.46, "services_rev_growth": 0.14},
        citations=[
            Citation(
                url="https://example.com/aapl-10q",
                title="AAPL 10-Q Q2 2026",
                source="edgar",
                fetched_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )
        ],
    )
    restored = AnalystOutput.model_validate_json(ao.model_dump_json())
    assert restored == ao
