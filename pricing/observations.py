"""观测整理：按门店商品保留价格、活动、可售库存与观测期间。

缺货行（销量被库存截断）不再被简单丢弃：它们在估计层被当作右截断观测处理，
而不是被当作真实低需求。历史上只返回非缺货行的 ``eligible`` /
``by_store_product`` 保留，供只使用完整观测的模型设定与既有调用使用。
"""

from collections import Counter


def eligible(rows: list[dict]) -> list[dict]:
    """价格与销量可观测且未发生缺货截断的完整观测。"""
    return [
        row
        for row in rows
        if not row.get("stockout")
        and row.get("price") is not None
        and row.get("units") is not None
    ]


def by_store_product(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """完整观测（剔除缺货行）按门店商品分组，保持输入顺序。"""
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in eligible(rows):
        groups.setdefault((row["store"], row["product"]), []).append(row)
    return groups


def _period_of(row: dict) -> str | int:
    return row.get("period", 0)


def select_groups(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """全部有效观测（含缺货截断行）按门店商品分组并按观测期间排序。

    每行须有 store/product/price/units；缺货行还应给出可售库存
    ``available``，用于表示截断点。同一门店商品下观测期间不可重复。
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if row.get("price") is None or row.get("units") is None:
            continue
        if row.get("stockout") and row.get("available") is None:
            # 兼容历史数据：未显式给可售库存时，观测销量本身即截断点
            row = {**row, "available": row["units"]}
        key = (row["store"], row["product"])
        groups.setdefault(key, []).append(dict(row))
    for key, history in groups.items():
        explicit = [_period_of(row) for row in history if "period" in row]
        duplicates = [period for period, count in Counter(explicit).items() if count > 1]
        if duplicates:
            raise ValueError(f"{key} 存在重复观测期间: {sorted(duplicates)}")
        history.sort(key=_period_of)
    return dict(sorted(groups.items()))


def observation_window(history: list[dict]) -> dict:
    """该门店商品被采用的观测期间与可用价格/活动支持范围。"""
    periods = [_period_of(row) for row in history]
    prices = [float(row["price"]) for row in history]
    activities = sorted({bool(row.get("activity")) for row in history})
    return {
        "periods": list(periods),
        "n_observations": len(history),
        "n_stockouts": sum(1 for row in history if row.get("stockout")),
        "price_min": min(prices),
        "price_max": max(prices),
        "activity_seen": activities,
    }
