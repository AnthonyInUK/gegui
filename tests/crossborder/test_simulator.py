from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crossborder.pricing.simulator import ProfitInputs, simulate_profit, sweep  # noqa: E402


class PricingSimulatorTest(unittest.TestCase):
    def test_simulate_profit_matches_hand_calculation(self):
        inp = ProfitInputs(
            sale_price=40,
            unit_cost=8,
            inbound_shipping_per_unit=2,
            fba_fee=5,
            referral_fee_pct=0.15,
            ads_acos=0.15,
            return_rate=0.03,
            storage_fee_per_unit=0.5,
        )

        result = simulate_profit(inp)

        # landed=10, referral=6, ads=6, returns=0.45
        # net=40-6-5-6-0.45-10-0.5 = 12.05
        self.assertAlmostEqual(result.landed_cost, 10.0)
        self.assertAlmostEqual(result.breakdown["referral"], 6.0)
        self.assertAlmostEqual(result.breakdown["ads"], 6.0)
        self.assertAlmostEqual(result.breakdown["returns"], 0.45)
        self.assertAlmostEqual(result.net_profit, 12.05)
        self.assertAlmostEqual(result.net_margin, 0.3013)
        self.assertAlmostEqual(result.roi, 1.205)
        # fixed=15.95, denom=0.70 -> 22.7857
        self.assertAlmostEqual(result.breakeven_price, 22.7857)
        self.assertAlmostEqual(result.breakeven_acos, 0.4513)
        self.assertEqual(result.verdict, "healthy")

    def test_breakeven_price_is_none_when_fee_and_acos_consume_price(self):
        result = simulate_profit(
            ProfitInputs(
                sale_price=20,
                unit_cost=8,
                referral_fee_pct=0.6,
                ads_acos=0.4,
            )
        )

        self.assertIsNone(result.breakeven_price)

    def test_verdict_boundaries(self):
        healthy = simulate_profit(
            ProfitInputs(sale_price=10, unit_cost=5, referral_fee_pct=0.1, ads_acos=0.1)
        )
        thin = simulate_profit(
            ProfitInputs(sale_price=10, unit_cost=6.5, referral_fee_pct=0.1, ads_acos=0.1)
        )
        marginal = simulate_profit(
            ProfitInputs(sale_price=10, unit_cost=7.5, referral_fee_pct=0.1, ads_acos=0.1)
        )
        loss = simulate_profit(
            ProfitInputs(sale_price=10, unit_cost=9, referral_fee_pct=0.1, ads_acos=0.1)
        )

        self.assertEqual(healthy.verdict, "healthy")
        self.assertEqual(thin.verdict, "thin")
        self.assertEqual(marginal.verdict, "marginal")
        self.assertEqual(loss.verdict, "loss")

    def test_sweep_sale_price_is_monotonic(self):
        inp = ProfitInputs(
            sale_price=40,
            unit_cost=8,
            inbound_shipping_per_unit=2,
            fba_fee=5,
            referral_fee_pct=0.15,
            ads_acos=0.15,
            return_rate=0.03,
        )

        rows = sweep(inp, "sale_price", 20, 60, steps=5)

        self.assertEqual(len(rows), 5)
        margins = [row["net_margin"] for row in rows]
        self.assertEqual(margins, sorted(margins))
        self.assertTrue(any(row["net_profit"] < 0 for row in rows[:1]) or rows[0]["net_profit"] < rows[-1]["net_profit"])
        self.assertTrue(any(row["net_margin"] >= 0 for row in rows))

    def test_invalid_sweep_variable_raises(self):
        with self.assertRaises(ValueError):
            sweep(ProfitInputs(sale_price=10, unit_cost=5), "bad", 1, 2)


class PricingSimulatorApiTest(unittest.TestCase):
    def test_http_simulate_and_sweep(self):
        try:
            from fastapi.testclient import TestClient
            from web.app import app
        except Exception as exc:  # pragma: no cover - environment guard
            self.skipTest(f"FastAPI TestClient unavailable: {exc}")

        client = TestClient(app)
        payload = {
            "sale_price": 40,
            "unit_cost": 8,
            "inbound_shipping_per_unit": 2,
            "fba_fee": 5,
        }
        sim = client.post("/api/pricing/simulate", json=payload)
        self.assertEqual(sim.status_code, 200)
        self.assertIn("net_profit", sim.json())

        swept = client.post(
            "/api/pricing/sweep",
            json={"inputs": payload, "variable": "ads_acos", "start": 0.1, "stop": 0.3, "steps": 3},
        )
        self.assertEqual(swept.status_code, 200)
        self.assertEqual(len(swept.json()), 3)

        bad = client.post(
            "/api/pricing/sweep",
            json={"inputs": payload, "variable": "bad", "start": 0, "stop": 1},
        )
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
