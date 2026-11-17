"""采购报价与确认。

报价的每一行都回溯到 :mod:`pricing.planning` 产出的需求证据：模型怎么选、
用了哪些观测、不确定性多大、为什么被留给人工，全部随报价冻结。确认订单
绑定当次采用的证据与方案；之后换模型只会产生新报价，不会改写已确认采购。

预算与在途的口径：

* 传入 ``stockroom`` 与到货期限 ``arrives_cutoff`` 时，可用库存自动合并
  期限内在途，已确认在途占用的预算从共享预算中扣除；
* 比较多份备选报价反复调用 :meth:`PurchaseDesk.quote` 不会重复占用，
  占用只在 :meth:`PurchaseDesk.approve` 成功时发生，且同一订单号重试确认
  是幂等的，不会再登记一遍在途或再加一次预算；
* 标记为 ``manual`` 的商品不给采购数量（不填零、不用全店平均遮盖），
  因此整单不可自动确认，必须先人工决定。
"""

from copy import deepcopy
import math

from .planning import demand_basis

_BUDGET_TOLERANCE = 1e-9


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

    def _committed_cost(self, stockroom) -> float:
        return 0.0 if stockroom is None else float(stockroom.committed_cost())

    def available_budget(self, stockroom=None) -> float:
        return self.budget - self._committed_cost(stockroom)

    def quote(
        self,
        rows: list[dict],
        proposed_price: float,
        on_hand: dict[tuple[str, str], int] | None = None,
        *,
        proposed_activity: bool = False,
        cycle_periods: int = 1,
        stockroom=None,
        arrives_cutoff: int | None = None,
    ) -> dict:
        on_hand = dict(on_hand or {})
        if stockroom is not None:
            if arrives_cutoff is None:
                raise ValueError("结合库存台账报价时必须给到货期限 arrives_cutoff")
            for key, units in stockroom.available_by(arrives_cutoff).items():
                on_hand[key] = on_hand.get(key, 0) + units
        committed = self._committed_cost(stockroom)
        basis = demand_basis(rows, proposed_price, proposed_activity, cycle_periods)

        items = []
        for evidence in basis:
            product = evidence["product"]
            terms = self.terms[product]
            line = {
                "store": evidence["store"],
                "product": product,
                "status": evidence["status"],
                "flags": list(evidence["flags"]),
                "manual_reasons": list(evidence["manual_reasons"]),
                "preferred_model": evidence["preferred_model"],
                "expected_units": evidence["expected_units"],
                "expected_units_interval": evidence["expected_units_interval"],
                "price_elasticity": evidence["price_elasticity"],
                "evidence": deepcopy(evidence),
            }
            if evidence["status"] == "manual":
                line.update({"gap_units": None, "order_units": None, "cost": None})
            else:
                expected = float(evidence["expected_units"])
                available = on_hand.get((evidence["store"], product), 0)
                gap = max(0.0, expected - available)
                order_units = math.ceil(gap / terms["pack_size"]) * terms["pack_size"]
                line.update(
                    {
                        "gap_units": gap,
                        "order_units": order_units,
                        "cost": order_units * float(terms["unit_cost"]),
                    }
                )
            items.append(line)

        new_cost = sum(item["cost"] or 0 for item in items)
        manual_items = [item for item in items if item["status"] == "manual"]
        quote = {
            "items": items,
            "total_cost": new_cost,
            "committed_cost": committed,
            "budget": self.budget,
            "remaining_budget": self.budget - committed - new_cost,
            "within_budget": committed + new_cost <= self.budget,
            "complete": not manual_items,
            "manual_count": len(manual_items),
            "proposed_price": float(proposed_price),
            "proposed_activity": bool(proposed_activity),
            "cycle_periods": cycle_periods,
            "arrives_cutoff": arrives_cutoff,
        }
        return quote

    def compare_options(self, options: list[dict]) -> list[dict]:
        """并排比较备选采购组合；只读，不产生任何预算占用。"""
        summary = []
        for index, quote in enumerate(options):
            summary.append(
                {
                    "option": index,
                    "total_cost": quote["total_cost"],
                    "committed_cost": quote["committed_cost"],
                    "remaining_budget": quote["remaining_budget"],
                    "within_budget": quote["within_budget"],
                    "complete": quote["complete"],
                    "manual_count": quote["manual_count"],
                    "proposed_price": quote["proposed_price"],
                    "proposed_activity": quote["proposed_activity"],
                    "order_lines": [
                        {
                            "store": item["store"],
                            "product": item["product"],
                            "status": item["status"],
                            "order_units": item["order_units"],
                            "cost": item["cost"],
                        }
                        for item in quote["items"]
                    ],
                }
            )
        return summary

    def approve(
        self,
        order_id: str,
        quote: dict,
        stockroom=None,
        arrives_at: int | None = None,
    ) -> dict:
        """确认报价：校验预算口径，幂等登记在途并冻结当次证据与方案。"""
        if not quote["complete"] or not quote["within_budget"]:
            raise ValueError("不能确认未定量或超预算的采购")
        if order_id in self.orders:
            if self.orders[order_id] != quote:
                raise ValueError("采购单已确认，不能被改写")
            # 重试确认同一报价：直接返回冻结副本，不再登记在途或占用预算
            return deepcopy(quote)
        if stockroom is not None:
            if arrives_at is None:
                raise ValueError("结合库存台账确认时必须给预计到货期 arrives_at")
            # 以台账当前口径复核，确认后采购、在途与剩余预算彼此一致
            if not math.isclose(stockroom.committed_cost(), quote["committed_cost"], abs_tol=_BUDGET_TOLERANCE):
                raise ValueError("台账已用预算与报价口径不一致，请基于最新在途重新报价")
            if stockroom.committed_cost() + quote["total_cost"] > self.budget + _BUDGET_TOLERANCE:
                raise ValueError("确认后超出共享预算")
            for line in [item for item in quote["items"] if item["order_units"]]:
                stockroom.register_incoming(
                    f"{order_id}:{line['store']}:{line['product']}",
                    line["store"],
                    line["product"],
                    int(line["order_units"]),
                    int(arrives_at),
                    committed_cost=float(line["cost"]),
                )
            if not math.isclose(
                stockroom.committed_cost(),
                quote["committed_cost"] + quote["total_cost"],
                abs_tol=_BUDGET_TOLERANCE,
            ):
                raise ValueError("确认后预算占用与报价不一致")
        self.orders[order_id] = deepcopy(quote)
        return deepcopy(quote)
