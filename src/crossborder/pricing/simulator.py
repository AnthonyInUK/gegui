"""Deterministic Amazon-style profit and pricing what-if simulator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from pydantic import BaseModel


class ProfitInputs(BaseModel):
    sale_price: float
    unit_cost: float
    inbound_shipping_per_unit: float = 0.0
    referral_fee_pct: float = 0.15
    fba_fee: float = 0.0
    storage_fee_per_unit: float = 0.0
    ads_acos: float = 0.15
    return_rate: float = 0.03
    other_per_unit: float = 0.0


class ProfitResult(BaseModel):
    inputs: ProfitInputs
    landed_cost: float
    breakdown: dict[str, float]
    net_profit: float
    net_margin: float
    roi: float | None
    breakeven_price: float | None
    breakeven_acos: float | None
    verdict: str
    note: str = (
        "Simulation uses configurable defaults such as referral fee, FBA fee, ACOS, "
        "and return rate. It is not a live Amazon fee quote."
    )


def simulate_profit(inp: ProfitInputs) -> ProfitResult:
    landed = inp.unit_cost + inp.inbound_shipping_per_unit
    referral = inp.sale_price * inp.referral_fee_pct
    ads = inp.sale_price * inp.ads_acos
    returns_cost = inp.return_rate * (landed + inp.fba_fee)
    net_profit = (
        inp.sale_price
        - referral
        - inp.fba_fee
        - ads
        - returns_cost
        - landed
        - inp.storage_fee_per_unit
        - inp.other_per_unit
    )
    net_margin = _safe_div(net_profit, inp.sale_price, fallback=0.0)
    roi = _safe_div(net_profit, landed, fallback=None)
    fixed_costs = landed + inp.fba_fee + returns_cost + inp.storage_fee_per_unit + inp.other_per_unit
    breakeven_denom = 1 - inp.referral_fee_pct - inp.ads_acos
    breakeven_price = fixed_costs / breakeven_denom if breakeven_denom > 0 else None
    breakeven_acos_raw = (
        (inp.sale_price * (1 - inp.referral_fee_pct) - fixed_costs) / inp.sale_price
        if inp.sale_price > 0
        else None
    )
    breakeven_acos = None
    if breakeven_acos_raw is not None and breakeven_acos_raw >= 0:
        breakeven_acos = min(1.0, breakeven_acos_raw)

    return ProfitResult(
        inputs=inp,
        landed_cost=round(landed, 4),
        breakdown={
            "landed": round(landed, 4),
            "referral": round(referral, 4),
            "fba": round(inp.fba_fee, 4),
            "ads": round(ads, 4),
            "returns": round(returns_cost, 4),
            "storage": round(inp.storage_fee_per_unit, 4),
            "other": round(inp.other_per_unit, 4),
        },
        net_profit=round(net_profit, 4),
        net_margin=round(net_margin, 4),
        roi=round(roi, 4) if roi is not None else None,
        breakeven_price=round(breakeven_price, 4) if breakeven_price is not None else None,
        breakeven_acos=round(breakeven_acos, 4) if breakeven_acos is not None else None,
        verdict=_verdict(net_margin),
    )


def sweep(
    inp: ProfitInputs,
    variable: str,
    start: float,
    stop: float,
    steps: int = 20,
) -> list[dict[str, Any]]:
    if variable not in {"sale_price", "unit_cost", "ads_acos", "return_rate"}:
        raise ValueError("variable must be one of sale_price, unit_cost, ads_acos, return_rate")
    if steps <= 0:
        raise ValueError("steps must be positive")
    if steps == 1:
        values = [start]
    else:
        step = (stop - start) / (steps - 1)
        values = [start + step * i for i in range(steps)]
    rows: list[dict[str, Any]] = []
    for value in values:
        result = simulate_profit(inp.model_copy(update={variable: value}))
        rows.append(
            {
                "x": round(value, 4),
                "variable": variable,
                "net_profit": result.net_profit,
                "net_margin": result.net_margin,
                "verdict": result.verdict,
            }
        )
    return rows


def _verdict(net_margin: float) -> str:
    if net_margin >= 0.2:
        return "healthy"
    if net_margin >= 0.1:
        return "thin"
    if net_margin < 0:
        return "loss"
    return "marginal"


def _safe_div(num: float, denom: float, *, fallback):
    return num / denom if denom else fallback


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic profit what-if simulation.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--sweep", nargs=3, metavar=("VARIABLE", "START", "STOP"))
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    inp = ProfitInputs.model_validate(payload)
    if args.sweep:
        variable, start, stop = args.sweep
        json.dump(
            sweep(inp, variable, float(start), float(stop), steps=args.steps),
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
    else:
        json.dump(simulate_profit(inp).model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
