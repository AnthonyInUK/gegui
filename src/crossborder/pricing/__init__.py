"""Price provider and injection helpers for cross-border product research."""

__all__ = [
    "KeepaPriceProvider",
    "ManualPriceProvider",
    "PriceProvider",
    "PriceProvenance",
    "PriceQuote",
    "ProfitInputs",
    "ProfitResult",
    "StubPriceProvider",
    "deep_dive_with_prices",
    "inject_real_prices",
    "simulate_profit",
    "sweep",
]


def __getattr__(name: str):
    if name in {"deep_dive_with_prices", "inject_real_prices"}:
        from crossborder.pricing.inject import deep_dive_with_prices, inject_real_prices

        return {
            "deep_dive_with_prices": deep_dive_with_prices,
            "inject_real_prices": inject_real_prices,
        }[name]
    if name in {"ProfitInputs", "ProfitResult", "simulate_profit", "sweep"}:
        from crossborder.pricing.simulator import ProfitInputs, ProfitResult, simulate_profit, sweep

        return {
            "ProfitInputs": ProfitInputs,
            "ProfitResult": ProfitResult,
            "simulate_profit": simulate_profit,
            "sweep": sweep,
        }[name]
    if name in {
        "KeepaPriceProvider",
        "ManualPriceProvider",
        "PriceProvider",
        "PriceProvenance",
        "PriceQuote",
        "StubPriceProvider",
    }:
        from crossborder.pricing.providers import (
            KeepaPriceProvider,
            ManualPriceProvider,
            PriceProvider,
            PriceProvenance,
            PriceQuote,
            StubPriceProvider,
        )

        return {
            "KeepaPriceProvider": KeepaPriceProvider,
            "ManualPriceProvider": ManualPriceProvider,
            "PriceProvider": PriceProvider,
            "PriceProvenance": PriceProvenance,
            "PriceQuote": PriceQuote,
            "StubPriceProvider": StubPriceProvider,
        }[name]
    raise AttributeError(name)
