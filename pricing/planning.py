"""采购前可审阅的需求依据。

对每个门店商品，在同一批观测上比较多种模型设定，给出：

* 观测期间、价格/活动支持范围、缺货截断次数；
* 各设定是否可识别、价格系数与标准误、采用的样本量；
* 推荐设定与其在给定零售价、活动与补货周期下的需求预测和不确定性；
* 显式的人工决定标记：估计不足、超出历史价格支持范围、价格与活动
  完全重叠、对模型设定敏感——这些商品 ``status='manual'``，不填零，
  也不用全店平均遮盖。
"""

from dataclasses import asdict

import numpy as np

from .estimate import candidate_fits
from .observations import observation_window, select_groups

# 设定间价格系数最大相对离散，超过即视为对设定敏感
SENSITIVITY_REL = 0.5
# 价格系数标准误相对系数本身的比例上限，超过视为弱证据
REL_PRECISION_LIMIT = 0.5
# 单期预测区间宽度相对点预测的比例上限，超过视为不确定性过大
INTERVAL_WIDTH_LIMIT = 1.0


def _serialize_fit(fit) -> dict:
    data = asdict(fit)
    data.pop("diagnostics", None)
    data["diagnostics"] = {
        key: value for key, value in fit.diagnostics.items() if key != "parameter_cov"
    }
    return data


def _coef_spread(fits: list) -> tuple[float, list[float]]:
    coefs = [fit.price_coef for fit in fits if fit.identified and fit.price_coef is not None]
    if len(coefs) < 2:
        return 0.0, coefs
    spread = (max(coefs) - min(coefs)) / max(abs(float(np.median(coefs))), 1e-9)
    return abs(spread), coefs


def _build_evidence(
    key: tuple[str, str],
    history: list[dict],
    proposed_price: float,
    proposed_activity: bool,
    cycle_periods: int,
) -> dict:
    store, product = key
    window = observation_window(history)
    fits = candidate_fits(history)
    identified = [fit for fit in fits if fit.identified]
    fit_by_name = {fit.name: fit for fit in fits}

    flags: set[str] = set()
    reasons: list[str] = []

    has_activity_variation = len(window["activity_seen"]) > 1
    if has_activity_variation and not fit_by_name["ols_activity"].identified:
        flags.add("price_activity_overlap")
        reasons.append("价格与活动完全重叠，无法分离价格弹性")

    if not identified:
        reasons.append(next((fit.reason for fit in fits if fit.reason), "没有可识别的模型设定"))
        return _manual_bundle(store, product, window, fits, flags, reasons, proposed_price, proposed_activity)

    if not (window["price_min"] <= float(proposed_price) <= window["price_max"]):
        flags.add("outside_historical_price_range")
        reasons.append(
            f"拟用价格 {proposed_price} 超出历史价格支持范围 "
            f"[{window['price_min']}, {window['price_max']}]，属于外推"
        )

    if window["n_stockouts"] > 0:
        flags.add("censored_demand")

    spread, _ = _coef_spread(fits)
    if spread > SENSITIVITY_REL:
        flags.add("specification_sensitive")
        reasons.append(f"模型设定间价格系数相对离散 {spread:.2f} 超过 {SENSITIVITY_REL}，需求对设定敏感")

    # 优先使用能容纳截断观测的 Tobit；否则用控制活动的 OLS；最后退回纯价格 OLS
    preferred = None
    if window["n_stockouts"] > 0 and fit_by_name["tobit"].identified:
        preferred = fit_by_name["tobit"]
    elif fit_by_name["ols_activity"].identified:
        preferred = fit_by_name["ols_activity"]
    else:
        preferred = fit_by_name["ols_price"]

    point = preferred.predict(proposed_price, proposed_activity)
    interval = preferred.prediction_interval(proposed_price, proposed_activity)
    if preferred.price_se is not None and preferred.price_coef:
        rel_precision = abs(preferred.price_se / preferred.price_coef)
        if rel_precision > REL_PRECISION_LIMIT:
            flags.add("weak_evidence")
            reasons.append(f"价格系数相对标准误 {rel_precision:.2f} 超过 {REL_PRECISION_LIMIT}，估计精度不足")
    if point is not None and interval is not None and abs(point) > 1e-9:
        rel_width = (interval[1] - interval[0]) / abs(point)
        if rel_width > INTERVAL_WIDTH_LIMIT:
            flags.add("weak_evidence")
            reasons.append(f"单期预测区间相对宽度 {rel_width:.2f} 超过 {INTERVAL_WIDTH_LIMIT}，不确定性过大")
    if window["n_observations"] < 3:
        # 信息性标记：小样本证据随报价保留，但不单独阻断定量
        flags.add("few_observations")

    elasticity = (
        preferred.price_coef * float(proposed_price) / point
        if point is not None and abs(point) > 1e-9 and preferred.price_coef is not None
        else None
    )

    if reasons:
        return _manual_bundle(store, product, window, fits, flags, reasons, proposed_price,
                              proposed_activity, preferred, point, interval, elasticity)

    cycle_point = max(0.0, point * cycle_periods)
    cycle_interval = _scale_interval(interval, cycle_periods, cycle_point)
    return {
        "store": store,
        "product": product,
        "status": "ok",
        "flags": sorted(flags),
        "manual_reasons": [],
        "window": window,
        "fits": [_serialize_fit(fit) for fit in fits],
        "preferred_model": preferred.name,
        "proposed_price": float(proposed_price),
        "proposed_activity": bool(proposed_activity),
        "cycle_periods": cycle_periods,
        "slope": preferred.price_coef,
        "point_demand_per_period": float(point),
        "period_interval": interval,
        "expected_units": cycle_point,
        "expected_units_interval": cycle_interval,
        "price_elasticity": elasticity,
    }


def _scale_interval(interval, cycle_periods: int, cycle_point: float):
    if interval is None:
        return None
    half_width = (interval[1] - interval[0]) / 2 * (cycle_periods ** 0.5)
    return (max(0.0, cycle_point - half_width), cycle_point + half_width)


def _manual_bundle(store, product, window, fits, flags, reasons, proposed_price,
                   proposed_activity, preferred=None, point=None, interval=None,
                   elasticity=None) -> dict:
    return {
        "store": store,
        "product": product,
        "status": "manual",
        "flags": sorted(flags),
        "manual_reasons": reasons,
        "window": window,
        "fits": [_serialize_fit(fit) for fit in fits],
        "preferred_model": preferred.name if preferred is not None else None,
        "proposed_price": float(proposed_price),
        "proposed_activity": bool(proposed_activity),
        # 人工决定项不给定量需求，调用方不得填零或用平均值遮盖；点预测仅作参考
        "slope": preferred.price_coef if preferred is not None else None,
        "point_demand_per_period": None if point is None else float(point),
        "period_interval": interval,
        "expected_units": None,
        "expected_units_interval": None,
        "price_elasticity": elasticity,
    }


def demand_basis(
    rows: list[dict],
    proposed_price: float,
    proposed_activity: bool = False,
    cycle_periods: int = 1,
) -> list[dict]:
    """全部门店商品的需求证据包，按门店商品排序。"""
    if cycle_periods <= 0:
        raise ValueError("补货周期所含期数必须为正")
    return [
        _build_evidence(key, history, proposed_price, proposed_activity, cycle_periods)
        for key, history in select_groups(rows).items()
    ]


def scenarios(rows: list[dict], proposed_price: float) -> list[dict]:
    """历史兼容接口：返回 slope/expected_units，人工项为 None（不填零）。"""
    return [
        {
            "store": evidence["store"],
            "product": evidence["product"],
            "slope": evidence["slope"],
            "expected_units": evidence["expected_units"],
        }
        for evidence in demand_basis(rows, proposed_price)
    ]
