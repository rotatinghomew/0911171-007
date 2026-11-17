import unittest

from pricing.observations import observation_window, select_groups
from pricing.estimate import candidate_fits, fit_ols, fit_tobit


class ObservationTests(unittest.TestCase):
    def test_stockout_rows_are_kept_as_censored_not_dropped(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 20, "available": 20, "stockout": True},
            {"store": "s", "product": "p", "period": 2, "price": 12, "units": 16, "available": 30},
        ]
        groups = select_groups(rows)
        history = groups[("s", "p")]
        self.assertEqual(len(history), 2)
        window = observation_window(history)
        self.assertEqual(window["n_stockouts"], 1)
        self.assertEqual(window["periods"], [1, 2])
        self.assertEqual(window["price_min"], 10.0)
        self.assertEqual(window["price_max"], 12.0)

    def test_duplicate_explicit_period_rejected(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 20},
            {"store": "s", "product": "p", "period": 1, "price": 11, "units": 18},
        ]
        with self.assertRaises(ValueError):
            select_groups(rows)

    def test_legacy_rows_without_period_are_tolerated(self):
        rows = [
            {"store": "s", "product": "p", "price": 10, "units": 20},
            {"store": "s", "product": "p", "price": 12, "units": 16},
        ]
        self.assertEqual(len(select_groups(rows)[("s", "p")]), 2)


class ModelSpecificationTests(unittest.TestCase):
    def test_ols_excludes_censored_rows_but_tobit_uses_them(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 12, "units": 18, "available": 40},
            {"store": "s", "product": "p", "period": 2, "price": 10, "units": 20, "available": 20, "stockout": True},
            {"store": "s", "product": "p", "period": 3, "price": 10, "units": 22, "available": 22, "stockout": True},
            {"store": "s", "product": "p", "period": 4, "price": 14, "units": 12, "available": 40},
            {"store": "s", "product": "p", "period": 5, "price": 12, "units": 16, "available": 40},
        ]
        fits = {fit.name: fit for fit in candidate_fits(rows)}
        self.assertTrue(fits["ols_price"].identified)
        self.assertEqual(fits["ols_price"].n_used, 3)
        self.assertEqual(fits["ols_price"].n_censored, 2)
        self.assertTrue(fits["tobit"].identified)
        self.assertEqual(fits["tobit"].n_used, 5)
        self.assertEqual(fits["tobit"].n_censored, 2)
        # 截断观测把需求往上托：Tobit 价格响应不会被低截断销量稀释成更平的斜率
        self.assertLess(fits["tobit"].price_coef, fits["ols_price"].price_coef)

    def test_tobit_reports_parameter_and_prediction_uncertainty(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 12, "units": 18, "available": 40},
            {"store": "s", "product": "p", "period": 2, "price": 10, "units": 20, "available": 20, "stockout": True},
            {"store": "s", "product": "p", "period": 3, "price": 10, "units": 22, "available": 22, "stockout": True},
            {"store": "s", "product": "p", "period": 4, "price": 14, "units": 12, "available": 40},
            {"store": "s", "product": "p", "period": 5, "price": 12, "units": 16, "available": 40},
        ]
        fit = fit_tobit(rows)
        self.assertIsNotNone(fit.sigma)
        interval = fit.prediction_interval(11)
        self.assertIsNotNone(interval)
        point = fit.predict(11)
        self.assertLess(interval[0], point)
        self.assertLess(point, interval[1])

    def test_perfect_price_activity_overlap_is_not_force_fitted(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 22, "activity": True},
            {"store": "s", "product": "p", "period": 2, "price": 10, "units": 24, "activity": True},
            {"store": "s", "product": "p", "period": 3, "price": 14, "units": 12, "activity": False},
            {"store": "s", "product": "p", "period": 4, "price": 14, "units": 10, "activity": False},
        ]
        activity_fit = fit_ols(rows, with_activity=True)
        self.assertFalse(activity_fit.identified)
        self.assertIsNone(activity_fit.price_coef)
        # 纯价格设定仍可识别，诊断信息保留
        self.assertTrue(fit_ols(rows, with_activity=False).identified)

    def test_single_price_cannot_identify_response(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 20},
            {"store": "s", "product": "p", "period": 2, "price": 10, "units": 22},
        ]
        for fit in candidate_fits(rows):
            self.assertFalse(fit.identified)

    def test_exact_two_point_fit_identifies_coef_without_uncertainty(self):
        rows = [
            {"store": "s", "product": "p", "price": 10, "units": 12},
            {"store": "s", "product": "p", "price": 12, "units": 8},
        ]
        fit = fit_ols(rows, with_activity=False)
        self.assertTrue(fit.identified)
        self.assertAlmostEqual(fit.price_coef, -2.0)
        self.assertIsNone(fit.price_se)
        self.assertTrue(fit.diagnostics["exact_fit"])

    def test_tobit_includes_activity_coef_when_effects_are_separable(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 12, "units": 18, "available": 40},
            {"store": "s", "product": "p", "period": 2, "price": 10, "units": 20, "available": 20, "stockout": True, "activity": True},
            {"store": "s", "product": "p", "period": 3, "price": 10, "units": 22, "available": 22, "stockout": True, "activity": True},
            {"store": "s", "product": "p", "period": 4, "price": 14, "units": 12, "available": 40},
            {"store": "s", "product": "p", "period": 5, "price": 12, "units": 16, "available": 40, "activity": True},
            {"store": "s", "product": "p", "period": 6, "price": 12, "units": 15, "available": 40},
        ]
        fit = fit_tobit(rows)
        self.assertTrue(fit.identified)
        self.assertIsNotNone(fit.activity_coef)
        self.assertEqual(fit.n_censored, 2)

    def test_all_censored_history_is_not_force_fitted(self):
        rows = [
            {"store": "s", "product": "p", "period": 1, "price": 10, "units": 20, "available": 20, "stockout": True},
            {"store": "s", "product": "p", "period": 2, "price": 12, "units": 16, "available": 16, "stockout": True},
        ]
        fit = fit_tobit(rows)
        self.assertFalse(fit.identified)
        self.assertIsNone(fit.price_coef)
        self.assertIn("截断", fit.reason)


if __name__ == "__main__":
    unittest.main()
