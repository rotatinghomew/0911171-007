import unittest

from pricing.planning import scenarios


class PricingTests(unittest.TestCase):
    def test_stockout_is_excluded_from_response_estimate(self):
        rows = [{"store": "s", "product": "p", "price": 10, "units": 20}, {"store": "s", "product": "p", "price": 12, "units": 16, "stockout": True}]
        self.assertIsNone(scenarios(rows, 11)[0]["slope"])

    def test_single_price_cannot_estimate_response(self):
        rows = [{"store": "s", "product": "p", "price": 10, "units": 20}]
        self.assertIsNone(scenarios(rows, 11)[0]["expected_units"])


if __name__ == "__main__":
    unittest.main()
