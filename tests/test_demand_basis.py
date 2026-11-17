import unittest

from pricing.planning import (
    INTERVAL_WIDTH_LIMIT,
    SENSITIVITY_REL,
    demand_basis,
    scenarios,
)


CENSORED_HISTORY = [
    {"store": "s1", "product": "p1", "period": 1, "price": 12, "units": 18, "available": 40},
    {"store": "s1", "product": "p1", "period": 2, "price": 10, "units": 20, "available": 20, "stockout": True, "activity": True},
    {"store": "s1", "product": "p1", "period": 3, "price": 10, "units": 22, "available": 22, "stockout": True, "activity": True},
    {"store": "s1", "product": "p1", "period": 4, "price": 14, "units": 12, "available": 40},
    {"store": "s1", "product": "p1", "period": 5, "price": 12, "units": 16, "available": 40, "activity": True},
    {"store": "s1", "product": "p1", "period": 6, "price": 12, "units": 15, "available": 40},
]


class DemandBasisTests(unittest.TestCase):
    def test_censored_history_prefers_tobit_and_keeps_evidence(self):
        evidence = demand_basis(CENSORED_HISTORY, 11, cycle_periods=2)[0]
        self.assertEqual(evidence["status"], "ok")
        self.assertEqual(evidence["preferred_model"], "tobit")
        self.assertIn("censored_demand", evidence["flags"])
        # 观测选择、窗口、各设定结果全部可审阅
        self.assertEqual(evidence["window"]["n_observations"], 6)
        self.assertEqual(evidence["window"]["n_stockouts"], 2)
        self.assertEqual({fit["name"] for fit in evidence["fits"]},
                         {"ols_price", "ols_activity", "tobit"})
        self.assertIsNotNone(evidence["expected_units_interval"])
        self.assertEqual(evidence["cycle_periods"], 2)

    def test_out_of_support_price_is_left_manual_not_extrapolated(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 20},
            {"store": "s", "product": "p", "period": 2, "price": 12, "units": 16},
            {"store": "s", "product": "p", "period": 3, "price": 11, "units": 18},
        ]
        evidence = demand_basis(rows, 20)[0]
        self.assertEqual(evidence["status"], "manual")
        self.assertIn("outside_historical_price_range", evidence["flags"])
        self.assertIsNone(evidence["expected_units"])
        self.assertTrue(evidence["manual_reasons"])

    def test_price_activity_overlap_is_left_manual(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 22, "activity": True},
            {"store": "s", "product": "p", "period": 2, "price": 10, "units": 24, "activity": True},
            {"store": "s", "product": "p", "period": 3, "price": 14, "units": 12, "activity": False},
            {"store": "s", "product": "p", "period": 4, "price": 14, "units": 10, "activity": False},
        ]
        evidence = demand_basis(rows, 12, proposed_activity=True)[0]
        self.assertEqual(evidence["status"], "manual")
        self.assertIn("price_activity_overlap", evidence["flags"])
        self.assertIsNone(evidence["expected_units"])

    def test_specification_sensitivity_is_flagged(self):
        # 截断观测与高噪声完整观测并存：OLS 与 Tobit 价格系数显著分化
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 25, "available": 25, "stockout": True},
            {"store": "s", "product": "p", "period": 2, "price": 11, "units": 26, "available": 26, "stockout": True},
            {"store": "s", "product": "p", "period": 3, "price": 12, "units": 12, "available": 40},
            {"store": "s", "product": "p", "period": 4, "price": 13, "units": 24, "available": 40},
            {"store": "s", "product": "p", "period": 5, "price": 14, "units": 9, "available": 40},
        ]
        evidence = demand_basis(rows, 12)[0]
        coefs = [fit["price_coef"] for fit in evidence["fits"] if fit["identified"]]
        median = sorted(coefs)[len(coefs) // 2]
        spread = abs((max(coefs) - min(coefs)) / abs(median))
        self.assertGreater(spread, SENSITIVITY_REL)
        self.assertIn("specification_sensitive", evidence["flags"])
        self.assertEqual(evidence["status"], "manual")

    def test_manual_items_never_become_zero_demand(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 20},
        ]
        evidence = demand_basis(rows, 10)[0]
        self.assertEqual(evidence["status"], "manual")
        self.assertIsNone(evidence["expected_units"])

    def test_legacy_scenario_interface_preserves_none_semantics(self):
        rows = [
            {"store": "s", "product": "p", "price": 10, "units": 20},
            {"store": "s", "product": "p", "price": 12, "units": 16},
        ]
        result = scenarios(rows, 11)[0]
        self.assertAlmostEqual(result["slope"], -2.0)
        self.assertIsNotNone(result["expected_units"])
        self.assertIsNone(scenarios(rows[:1], 11)[0]["expected_units"])

    def test_interval_threshold_constants_are_positive(self):
        self.assertGreater(SENSITIVITY_REL, 0)
        self.assertGreater(INTERVAL_WIDTH_LIMIT, 0)


if __name__ == "__main__":
    unittest.main()
