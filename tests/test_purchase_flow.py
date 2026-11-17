import math
import unittest

from pricing.purchasing import PurchaseDesk
from pricing.stockroom import Stockroom


HISTORY = [
    {"store": "s1", "product": "p1", "period": 1, "price": 10, "units": 20},
    {"store": "s1", "product": "p1", "period": 2, "price": 12, "units": 16},
    {"store": "s1", "product": "p1", "period": 3, "price": 11, "units": 18},
    {"store": "s1", "product": "p1", "period": 4, "price": 13, "units": 14},
]
TERMS = [{"product": "p1", "pack_size": 5, "unit_cost": 2}]


class QuotationFlowTests(unittest.TestCase):
    def test_incoming_within_cutoff_covers_demand_and_is_not_double_counted_across_quotes(self):
        stockroom = Stockroom({("s1", "p1"): 2})
        stockroom.register_incoming("inc-1", "s1", "p1", 6, arrives_at=10, committed_cost=12)
        desk = PurchaseDesk(TERMS, budget=100)

        before = desk.quote(HISTORY, 11, stockroom=stockroom, arrives_cutoff=9)
        after = desk.quote(HISTORY, 11, stockroom=stockroom, arrives_cutoff=10)
        # 期限内在途合并进可用位置；反复报价不改变台账占用
        self.assertGreater(before["items"][0]["order_units"], after["items"][0]["order_units"])
        self.assertEqual(stockroom.committed_cost(), 12)
        another = desk.quote(HISTORY, 12, stockroom=stockroom, arrives_cutoff=10)
        self.assertEqual(stockroom.committed_cost(), 12)
        self.assertEqual(another["committed_cost"], 12)

    def test_quote_requires_cutoff_when_stockroom_given(self):
        desk = PurchaseDesk(TERMS, 100)
        with self.assertRaises(ValueError):
            desk.quote(HISTORY, 11, stockroom=Stockroom({}))

    def test_committed_budget_is_deducted_from_shared_budget(self):
        stockroom = Stockroom({})
        stockroom.register_incoming("inc-1", "s1", "p1", 5, arrives_at=10, committed_cost=90)
        desk = PurchaseDesk(TERMS, budget=100)
        quote = desk.quote(HISTORY, 11, stockroom=stockroom, arrives_cutoff=10)
        self.assertEqual(quote["committed_cost"], 90)
        self.assertEqual(quote["remaining_budget"], 100 - 90 - quote["total_cost"])
        self.assertFalse(quote["within_budget"])
        self.assertEqual(desk.available_budget(stockroom), 10)

    def test_manual_item_blocks_approval_and_never_gets_zero_units(self):
        rows = HISTORY + [
            {"store": "s2", "product": "p2", "period": 1, "price": 10, "units": 22, "activity": True},
            {"store": "s2", "product": "p2", "period": 2, "price": 10, "units": 24, "activity": True},
            {"store": "s2", "product": "p2", "period": 3, "price": 14, "units": 12, "activity": False},
            {"store": "s2", "product": "p2", "period": 4, "price": 14, "units": 10, "activity": False},
        ]
        terms = TERMS + [{"product": "p2", "pack_size": 4, "unit_cost": 3}]
        stockroom = Stockroom({})
        desk = PurchaseDesk(terms, budget=500)
        quote = desk.quote(rows, 11, stockroom=stockroom, arrives_cutoff=10)
        manual = next(item for item in quote["items"] if item["product"] == "p2")
        self.assertEqual(manual["status"], "manual")
        self.assertIsNone(manual["order_units"])
        self.assertFalse(quote["complete"])
        with self.assertRaises(ValueError):
            desk.approve("po-1", quote, stockroom=stockroom, arrives_at=12)
        # 被拦截的确认没有占用任何预算
        self.assertEqual(stockroom.committed_cost(), 0)

    def test_compare_options_is_read_only(self):
        stockroom = Stockroom({})
        desk = PurchaseDesk(TERMS, budget=100)
        q1 = desk.quote(HISTORY, 10, stockroom=stockroom, arrives_cutoff=10)
        q2 = desk.quote(HISTORY, 13, stockroom=stockroom, arrives_cutoff=10)
        summary = desk.compare_options([q1, q2])
        self.assertEqual(len(summary), 2)
        self.assertEqual(stockroom.committed_cost(), 0)
        self.assertNotEqual(summary[0]["total_cost"], summary[1]["total_cost"])


class ApprovalConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.stockroom = Stockroom({("s1", "p1"): 1})
        self.stockroom.register_incoming("inc-old", "s1", "p1", 4, arrives_at=10, committed_cost=8)
        self.desk = PurchaseDesk(TERMS, budget=100)
        self.quote = self.desk.quote(HISTORY, 11, stockroom=self.stockroom, arrives_cutoff=10)

    def test_approval_registers_incoming_and_keeps_budget_consistent(self):
        approved = self.desk.approve("po-1", self.quote, stockroom=self.stockroom, arrives_at=12)
        expected_committed = 8 + self.quote["total_cost"]
        self.assertEqual(self.stockroom.committed_cost(), expected_committed)
        self.assertEqual(self.desk.available_budget(self.stockroom), 100 - expected_committed)
        shipment = self.stockroom.incoming["po-1:s1:p1"]
        self.assertEqual(shipment["units"], approved["items"][0]["order_units"])
        self.assertEqual(shipment["committed_cost"], approved["items"][0]["cost"])

    def test_retry_approval_does_not_register_or_charge_again(self):
        self.desk.approve("po-1", self.quote, stockroom=self.stockroom, arrives_at=12)
        committed_after_first = self.stockroom.committed_cost()
        lines_after_first = len(self.stockroom.incoming)
        self.desk.approve("po-1", self.quote, stockroom=self.stockroom, arrives_at=12)
        self.assertEqual(self.stockroom.committed_cost(), committed_after_first)
        self.assertEqual(len(self.stockroom.incoming), lines_after_first)

    def test_receive_does_not_erase_committed_budget(self):
        self.desk.approve("po-1", self.quote, stockroom=self.stockroom, arrives_at=12)
        on_hand_before = dict(self.stockroom.on_hand)
        self.stockroom.receive("po-1:s1:p1", 12)
        self.stockroom.receive("po-1:s1:p1", 13)
        self.assertEqual(
            self.stockroom.on_hand[("s1", "p1")],
            on_hand_before[("s1", "p1")] + self.quote["items"][0]["order_units"],
        )
        self.assertEqual(self.stockroom.committed_cost(), 8 + self.quote["total_cost"])

    def test_approved_order_binds_evidence_and_is_not_rewritten_by_new_model(self):
        approved = self.desk.approve("po-1", self.quote, stockroom=self.stockroom, arrives_at=12)
        evidence = approved["items"][0]["evidence"]
        self.assertEqual(evidence["preferred_model"], approved["items"][0]["preferred_model"])
        self.assertIn("fits", evidence)
        self.assertEqual(evidence["window"]["n_observations"], 4)
        # 之后换价格/模型得到新报价，不能改写已确认采购
        new_quote = self.desk.quote(HISTORY, 12, stockroom=self.stockroom, arrives_cutoff=10)
        with self.assertRaises(ValueError):
            self.desk.approve("po-1", new_quote, stockroom=self.stockroom, arrives_at=12)
        # 冻结的证据不被外部修改污染
        stored_model = self.desk.orders["po-1"]["items"][0]["evidence"]["preferred_model"]
        approved["items"][0]["evidence"]["preferred_model"] = "tampered"
        self.assertEqual(
            self.desk.orders["po-1"]["items"][0]["evidence"]["preferred_model"],
            stored_model,
        )

    def test_approval_rejects_stale_budget_basis(self):
        # 报价之后台账新增了在途占用，确认时必须以最新口径拦截
        other = Stockroom({("s1", "p1"): 1})
        other.register_incoming("inc-old", "s1", "p1", 4, arrives_at=10, committed_cost=8)
        other.register_incoming("inc-late", "s1", "p1", 3, arrives_at=11, committed_cost=80)
        with self.assertRaises(ValueError):
            self.desk.approve("po-1", self.quote, stockroom=other, arrives_at=12)

    def test_legacy_approval_without_stockroom_still_works(self):
        desk = PurchaseDesk(TERMS, 100)
        quote = desk.quote(HISTORY, 11, {("s1", "p1"): 1})
        approved = desk.approve("legacy-1", quote)
        self.assertEqual(approved["total_cost"], quote["total_cost"])

    def test_order_quantity_is_traceable_to_evidence_and_pack_rules(self):
        stockroom = Stockroom({("s1", "p1"): 3})
        stockroom.register_incoming("inc-1", "s1", "p1", 2, arrives_at=10, committed_cost=4)
        desk = PurchaseDesk(TERMS, budget=200)
        quote = desk.quote(HISTORY, 11, stockroom=stockroom, arrives_cutoff=10, cycle_periods=2)
        item = quote["items"][0]
        evidence = item["evidence"]
        # 可用 = 现货 3 + 期限内在途 2；缺口按箱规 5 向上取整
        available = 3 + 2
        expected_gap = max(0.0, evidence["expected_units"] - available)
        expected_units = math.ceil(expected_gap / 5) * 5
        self.assertEqual(item["gap_units"], expected_gap)
        self.assertEqual(item["order_units"], expected_units)
        self.assertEqual(item["cost"], expected_units * 2)
        # 证据窗口确实来自这 4 条观测，没有混入其他门店商品
        self.assertEqual(evidence["window"]["n_observations"], 4)
        self.assertEqual(evidence["window"]["periods"], [1, 2, 3, 4])
        # 不确定性区间随报价冻结，且包含点预测
        low, high = item["expected_units_interval"]
        self.assertLessEqual(low, item["expected_units"])
        self.assertLessEqual(item["expected_units"], high)


if __name__ == "__main__":
    unittest.main()
