import unittest

from pricing.purchasing import PurchaseDesk
from pricing.stockroom import Stockroom


class StockroomTests(unittest.TestCase):
    def test_existing_incoming_changes_purchase_but_receipt_does_not_double_it(self):
        stockroom = Stockroom({('s1', 'p1'): 1})
        stockroom.register_incoming('old', 's1', 'p1', 5, 10)
        desk = PurchaseDesk([{'product': 'p1', 'pack_size': 5, 'unit_cost': 2}], 100)
        history = [{'store': 's1', 'product': 'p1', 'price': 10, 'units': 12}, {'store': 's1', 'product': 'p1', 'price': 12, 'units': 8}]
        early = desk.quote(history, 10, stockroom.available_by(9))
        later = desk.quote(history, 10, stockroom.available_by(10))
        self.assertEqual(early['items'][0]['order_units'], 15)
        self.assertEqual(later['items'][0]['order_units'], 10)
        stockroom.receive('old', 10)
        stockroom.receive('old', 11)
        self.assertEqual(stockroom.available_by(20)[('s1', 'p1')], 6)

    def test_conflicting_incoming_identifier_is_not_silently_reused(self):
        stockroom = Stockroom({})
        stockroom.register_incoming('old', 's1', 'p1', 5, 10)
        with self.assertRaises(ValueError):
            stockroom.register_incoming('old', 's1', 'p1', 6, 10)
