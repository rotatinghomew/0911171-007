from copy import deepcopy
import math

from .planning import scenarios


class PurchaseDesk:
    def __init__(self, terms: list[dict], budget: float) -> None:
        if budget < 0:
            raise ValueError("预算不能为负")
        self.terms = {row["product"]: deepcopy(row) for row in terms}
        self.budget = budget
        self.orders: dict[str, dict] = {}
        for row in self.terms.values():
            if int(row["pack_size"]) <= 0 or float(row["unit_cost"]) <= 0:
                raise ValueError("包装规格和单价必须为正")

    def quote(self, rows: list[dict], proposed_price: float, on_hand: dict[tuple[str, str], int]) -> dict:
        items = []
        for result in scenarios(rows, proposed_price):
            product = result["product"]
            terms = self.terms[product]
            expected = result["expected_units"]
            missing = None if expected is None else max(0, expected - on_hand.get((result["store"], product), 0))
            units = None if missing is None else math.ceil(missing / terms["pack_size"]) * terms["pack_size"]
            items.append({**result, "order_units": units, "cost": None if units is None else units * terms["unit_cost"]})
        cost = sum(item["cost"] or 0 for item in items)
        return {"items": items, "total_cost": cost, "within_budget": cost <= self.budget, "complete": all(item["order_units"] is not None for item in items)}

    def approve(self, order_id: str, quote: dict) -> dict:
        if not quote["complete"] or not quote["within_budget"]:
            raise ValueError("不能确认未定量或超预算的采购")
        if order_id in self.orders and self.orders[order_id] != quote:
            raise ValueError("采购单已确认，不能被改写")
        self.orders[order_id] = deepcopy(quote)
        return deepcopy(quote)
