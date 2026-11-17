import unittest

from pricing.purchasing import PurchaseDesk


class PurchasingTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            {"store": "s1", "product": "p1", "price": 10, "units": 12},
            {"store": "s1", "product": "p1", "price": 12, "units": 8},
        ]
        self.terms = [{"product": "p1", "pack_size": 5, "unit_cost": 2}]

    def test_quotation_rounds_purchase_to_packs_and_freezes_approval(self):
        desk = PurchaseDesk(self.terms, 100)
        quote = desk.quote(self.history, 10, {("s1", "p1"): 1})
        self.assertEqual(quote["items"][0]["order_units"], 15)
        self.assertEqual(quote["total_cost"], 30)
        desk.approve("order1", quote)
        quote["total_cost"] = 0
        self.assertEqual(desk.orders["order1"]["total_cost"], 30)

    def test_budget_and_unknown_demand_block_approval(self):
        desk = PurchaseDesk(self.terms, 1)
        with self.assertRaises(ValueError):
            desk.approve("order1", desk.quote(self.history, 10, {}))
        with self.assertRaises(ValueError):
            desk.approve("order2", desk.quote(self.history[:1], 10, {}))
