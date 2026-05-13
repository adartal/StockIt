"""Deterministic risk post-processor for synthesized Plans.

The synthesizer (M5b) hands a candidate Plan to ``apply_risk_rules``, which
sizes the position from capital + per-trade risk, validates that a stop
exists strictly below entry, and surfaces concentration / oversize warnings.

Hard violations (currently: missing or non-protective stop) raise
``RiskRuleViolation``; the orchestrator catches it and re-prompts synth
once before giving up.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from decimal import Decimal

from app.models import UserRiskConfig, WatchlistItem
from app.pipeline.schema import Plan, RiskFlag, Sizing

SectorLookup = Callable[[str], str | None]

SECTOR_CONCENTRATION_THRESHOLD = 2


class RiskRuleViolation(Exception):  # noqa: N818 — name is contract from briefing
    """Hard risk-rule failure. Orchestrator catches this to re-prompt synth."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def apply_risk_rules(
    plan: Plan,
    capital: Decimal,
    risk_config: UserRiskConfig,
    existing_watchlist: list[WatchlistItem],
    existing_plans: list[Plan],
    sector_lookup: SectorLookup | None = None,
) -> tuple[Plan, list[RiskFlag]]:
    """Apply the four M5a risk rules and return (updated_plan, new_flags).

    Rules:
      1. stop_required (hard): stop must exist and sit strictly below entry[0].
      2. R-sizing (override): shares = floor(capital * risk_pct% / (entry - stop)).
      3. sector_concentration (warn): >2 existing positions in the new sector.
      4. oversized_position (warn): dollar_exposure > capital * max_position_pct%.
    """
    # Rule 1 — hard stop check (long-only assumption).
    if plan.stop is None:
        raise RiskRuleViolation("stop_required", "Plan is missing a stop.")
    entry_price = Decimal(plan.entry.levels[0])
    stop_price = Decimal(plan.stop.price)
    if stop_price >= entry_price:
        raise RiskRuleViolation(
            "stop_required",
            f"Stop {stop_price} is not below entry {entry_price}.",
        )

    # Rule 2 — derive sizing from capital and risk-per-trade.
    r_value = entry_price - stop_price
    risk_pct = Decimal(str(risk_config.risk_per_trade_pct))
    risk_dollars = capital * risk_pct / Decimal("100")
    shares = int(math.floor(risk_dollars / r_value))
    dollar_exposure = Decimal(shares) * entry_price
    new_sizing = Sizing(
        risk_pct=float(risk_pct),
        shares=shares,
        dollar_exposure=dollar_exposure,
        R_value=r_value,
    )

    flags: list[RiskFlag] = []

    # Rule 3 — sector concentration warning.
    if sector_lookup is not None:
        new_sector = sector_lookup(plan.ticker)
        if new_sector is not None:
            other_tickers: set[str] = {
                item.ticker for item in existing_watchlist if item.ticker != plan.ticker
            }
            other_tickers.update(
                p.ticker for p in existing_plans if p.ticker != plan.ticker
            )
            matches = sum(1 for t in other_tickers if sector_lookup(t) == new_sector)
            if matches > SECTOR_CONCENTRATION_THRESHOLD:
                flags.append(
                    RiskFlag(
                        severity="warn",
                        code="sector_concentration",
                        message=(
                            f"{matches} existing positions in sector "
                            f"'{new_sector}' (threshold {SECTOR_CONCENTRATION_THRESHOLD})."
                        ),
                    )
                )

    # Rule 4 — oversized-position warning.
    max_pct = Decimal(str(risk_config.max_position_pct))
    max_dollars = capital * max_pct / Decimal("100")
    if dollar_exposure > max_dollars:
        flags.append(
            RiskFlag(
                severity="warn",
                code="oversized_position",
                message=(
                    f"Position exposure {dollar_exposure} exceeds cap "
                    f"{max_dollars} ({risk_config.max_position_pct}% of capital)."
                ),
            )
        )

    combined_flags = list(plan.risk_flags) + flags
    updated_plan = plan.model_copy(
        update={"sizing": new_sizing, "risk_flags": combined_flags}
    )
    return updated_plan, flags


__all__ = ["RiskRuleViolation", "SectorLookup", "apply_risk_rules"]
