"""本地端到端例子：从观测选择到采购决策的完整链路。

运行 ``python -m pricing.demo``。例子是合成数据，只用于流程验证，
销量与价格的关联不自动构成因果结论。
"""

from .purchasing import PurchaseDesk
from .stockroom import Stockroom


def main() -> None:
    rows = [
        # s1/p1：常规价格响应，含两期被库存截断的促销周；
        # 活动也在非促销价出现过，价格效应与活动效应可以分离
        {"store": "s1", "product": "p1", "period": 1, "price": 12, "units": 18, "available": 40},
        {"store": "s1", "product": "p1", "period": 2, "price": 10, "units": 20, "available": 20, "stockout": True, "activity": True},
        {"store": "s1", "product": "p1", "period": 3, "price": 10, "units": 22, "available": 22, "stockout": True, "activity": True},
        {"store": "s1", "product": "p1", "period": 4, "price": 14, "units": 12, "available": 40},
        {"store": "s1", "product": "p1", "period": 5, "price": 12, "units": 16, "available": 40, "activity": True},
        {"store": "s1", "product": "p1", "period": 6, "price": 12, "units": 15, "available": 40},
        # s2/p2：价格与活动完全重叠，弹性不可识别
        {"store": "s2", "product": "p2", "period": 1, "price": 10, "units": 22, "activity": True},
        {"store": "s2", "product": "p2", "period": 2, "price": 10, "units": 24, "activity": True},
        {"store": "s2", "product": "p2", "period": 3, "price": 14, "units": 12, "activity": False},
        {"store": "s2", "product": "p2", "period": 4, "price": 14, "units": 10, "activity": False},
        # s1/p3：样本少，证据随报价保留为信息性标记
        {"store": "s1", "product": "p3", "period": 1, "price": 10, "units": 9},
        {"store": "s1", "product": "p3", "period": 2, "price": 12, "units": 7},
    ]

    stockroom = Stockroom({("s1", "p1"): 4, ("s2", "p2"): 0, ("s1", "p3"): 0})
    # 已确认在途：期限内到货，且已占用 12 元共享预算
    stockroom.register_incoming("incoming-p1", "s1", "p1", 6, arrives_at=10, committed_cost=12)

    desk = PurchaseDesk(
        [
            {"product": "p1", "pack_size": 5, "unit_cost": 2},
            {"product": "p2", "pack_size": 4, "unit_cost": 3},
            {"product": "p3", "pack_size": 2, "unit_cost": 4},
        ],
        budget=150,
    )

    quote_a = desk.quote(rows, 11, stockroom=stockroom, arrives_cutoff=10, cycle_periods=2)
    quote_b = desk.quote(rows, 12, stockroom=stockroom, arrives_cutoff=10, cycle_periods=2)

    print("== 备选采购组合比较（比较不产生预算占用） ==")
    for option in desk.compare_options([quote_a, quote_b]):
        print(option)

    print("\n== 逐门店商品的需求依据 ==")
    for item in quote_a["items"]:
        print(f"{item['store']}/{item['product']} status={item['status']} "
              f"model={item['preferred_model']} flags={item['flags']}")
        if item["status"] == "manual":
            for reason in item["manual_reasons"]:
                print(f"  留人工: {reason}")
        else:
            interval = item["expected_units_interval"]
            interval_text = "不可估" if interval is None else f"({interval[0]:.1f}, {interval[1]:.1f})"
            print(f"  周期需求={item['expected_units']:.1f} 区间={interval_text} "
                  f"采购={item['order_units']} 成本={item['cost']} 弹性={item['price_elasticity']:.2f}")

    print(f"\n报价A: 新增支出={quote_a['total_cost']} 已占用={quote_a['committed_cost']} "
          f"剩余预算={quote_a['remaining_budget']} 可自动确认={quote_a['complete']}")

    # 含人工项的整单不能确认，避免把未定量商品当零需求
    try:
        desk.approve("po-a", quote_a, stockroom=stockroom, arrives_at=12)
    except ValueError as exc:
        print(f"含人工项的整单确认被拦截: {exc}")

    # 人工决定后以只含可定量商品的证据重新报价，再走既有确认入口
    reviewed_rows = [row for row in rows if row["product"] != "p2"]
    final_quote = desk.quote(reviewed_rows, 11, stockroom=stockroom, arrives_cutoff=10, cycle_periods=2)
    approved = desk.approve("po-final", final_quote, stockroom=stockroom, arrives_at=12)
    print(f"\n已确认 {approved['items'][0]['store']}/{approved['items'][0]['product']}: "
          f"数量={approved['items'][0]['order_units']} 证据模型={approved['items'][0]['preferred_model']}")
    print(f"确认后台账已用预算={stockroom.committed_cost()} 剩余预算={desk.available_budget(stockroom)}")

    # 重试确认同一订单：不再登记一遍在途、不再加一次预算
    desk.approve("po-final", final_quote, stockroom=stockroom, arrives_at=12)
    print(f"重试确认后在途条数={len(stockroom.incoming)} 已用预算={stockroom.committed_cost()}（保持不变）")

    # 之后换模型/换价格产生的是新报价，不能改写已确认采购
    try:
        desk.approve("po-final", quote_b, stockroom=stockroom, arrives_at=12)
    except ValueError as exc:
        print(f"改写已确认订单被拦截: {exc}")


if __name__ == "__main__":
    main()
