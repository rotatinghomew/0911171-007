"""价格响应模型设定与不确定性。

提供三种可以互相比较的设定，均以截距 + 价格系数为核心：

* ``ols_price``：仅价格的普通最小二乘（只用未截断观测）；
* ``ols_activity``：价格 + 活动指示的普通最小二乘（只用未截断观测）；
* ``tobit``：右截断正态极大似然，缺货行作为截断观测参与估计，
  截断点为该期可售库存，销量被库存截断不会被当成真实低需求。

每个设定都返回价格系数标准误、残差尺度与预测区间，便于上游判断
估计精度与设定敏感度。识别不了（设计矩阵秩不足，如价格与活动完全
重叠、价格无变化）时返回 ``identified=False`` 而不是硬给一个数。
"""

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, stats


@dataclass
class Fit:
    name: str
    identified: bool
    intercept: float | None = None
    price_coef: float | None = None
    activity_coef: float | None = None
    price_se: float | None = None
    activity_se: float | None = None
    sigma: float | None = None
    n_used: int = 0
    n_censored: int = 0
    reason: str | None = None
    converged: bool = True
    diagnostics: dict = field(default_factory=dict)

    def predict(self, price: float, activity: bool = False) -> float | None:
        if not self.identified or self.intercept is None or self.price_coef is None:
            return None
        value = self.intercept + self.price_coef * float(price)
        if self.activity_coef is not None and activity:
            value += self.activity_coef
        return float(value)

    def prediction_interval(
        self, price: float, activity: bool = False, level: float = 0.9
    ) -> tuple[float, float] | None:
        """在给定价格/活动处的预测区间（含参数与残差不确定性）。"""
        point = self.predict(price, activity)
        if point is None or self.sigma is None or self.price_se is None:
            return None
        design = np.array([1.0, float(price), 1.0 if activity else 0.0])
        if self.activity_coef is None:
            design = design[:2]
        cov = self._covariance()
        if np.any(np.isnan(cov)):
            return None
        se_pred = float(np.sqrt(self.sigma**2 + design @ cov @ design))
        z = stats.norm.ppf(1 - (1 - level) / 2)
        return float(point - z * se_pred), float(point + z * se_pred)

    def _covariance(self) -> np.ndarray:
        cov = np.asarray(self.diagnostics.get("parameter_cov"), dtype=float)
        # Tobit 的协方差末行末列属于 log_sigma，回归参数只取前若干行列
        n_reg = 3 if self.activity_coef is not None else 2
        return cov[:n_reg, :n_reg]


def _design_matrix(rows: list[dict], with_activity: bool) -> np.ndarray:
    columns = [np.ones(len(rows)), np.array([float(r["price"]) for r in rows])]
    if with_activity:
        columns.append(np.array([1.0 if r.get("activity") else 0.0 for r in rows]))
    return np.column_stack(columns)


def _unidentifiable(name: str, n_used: int, reason: str, n_censored: int = 0) -> Fit:
    return Fit(
        name=name,
        identified=False,
        price_coef=None,
        n_used=n_used,
        n_censored=n_censored,
        reason=reason,
    )


def fit_ols(rows: list[dict], with_activity: bool) -> Fit:
    """普通最小二乘；缺货截断行不参与，避免把截断销量当低需求。"""
    name = "ols_activity" if with_activity else "ols_price"
    complete = [row for row in rows if not row.get("stockout")]
    n_censored = len(rows) - len(complete)
    if len(complete) < 2:
        return _unidentifiable(name, len(complete), "可比完整观测不足", n_censored)
    x = _design_matrix(complete, with_activity)
    y = np.array([float(r["units"]) for r in complete])
    rank = np.linalg.matrix_rank(x)
    if rank < x.shape[1]:
        return _unidentifiable(name, len(complete), "设计矩阵秩不足，变量完全重叠或价格无变化", n_censored)
    beta, residuals, _, _ = np.linalg.lstsq(x, y, rcond=None)
    dof = len(complete) - x.shape[1]
    rss = float(residuals[0]) if residuals.size else float(np.sum((y - x @ beta) ** 2))
    if dof <= 0:
        # 恰好可拟合但无残差自由度：系数可识别，不确定性不可估
        sigma = 0.0
        cov = np.zeros((x.shape[1], x.shape[1]))
        se = np.full(x.shape[1], np.nan)
        exact_fit = True
    else:
        sigma2 = rss / dof
        cov = sigma2 * np.linalg.inv(x.T @ x)
        se = np.sqrt(np.diag(cov))
        sigma = float(np.sqrt(sigma2))
        exact_fit = False
    total_ss = float(np.sum((y - y.mean()) ** 2))
    return Fit(
        name=name,
        identified=True,
        intercept=float(beta[0]),
        price_coef=float(beta[1]),
        activity_coef=float(beta[2]) if with_activity else None,
        price_se=None if np.isnan(se[1]) else float(se[1]),
        activity_se=None if with_activity and np.isnan(se[2]) else (float(se[2]) if with_activity else None),
        sigma=sigma,
        n_used=len(complete),
        n_censored=n_censored,
        diagnostics={"parameter_cov": cov,
                     "r_squared": 1.0 if total_ss == 0 else 1 - rss / total_ss,
                     "exact_fit": exact_fit},
    )


def _tobit_neg_log_likelihood(params: np.ndarray, x: np.ndarray, y: np.ndarray, censor: np.ndarray) -> float:
    intercept, price_coef, *rest = params
    activity_coef = rest[0] if x.shape[1] == 3 else None
    log_sigma = rest[-1]
    sigma = np.exp(log_sigma)
    mean = intercept + price_coef * x[:, 1]
    if activity_coef is not None:
        mean = mean + activity_coef * x[:, 2]
    uncensored = ~censor
    ll_uncensored = np.sum(stats.norm.logpdf(y[uncensored], loc=mean[uncensored], scale=sigma))
    # 右截断：真实需求 >= 观测到的截断销量（即可售库存）
    ll_censored = np.sum(stats.norm.logsf(y[censor] - mean[censor], scale=sigma))
    total = ll_uncensored + ll_censored
    return -total if np.isfinite(total) else 1e12


def fit_tobit(rows: list[dict]) -> Fit:
    """右截断正态 MLE；缺货行以截断点参与，全部观测都被使用。"""
    censored_rows = [row for row in rows if row.get("stockout")]
    complete = [row for row in rows if not row.get("stockout")]
    if not censored_rows:
        return _unidentifiable("tobit", len(complete), "没有截断观测，Tobit 与 OLS 等价，不重复设定")
    if not complete:
        # 只有截断观测时似然过弱、斜率符号都不可靠，缺少可比观测不硬算
        return _unidentifiable("tobit", 0, "全部观测均被库存截断，缺少可比完整观测", len(censored_rows))
    with_activity = (
        any(row.get("activity") for row in rows)
        and any(not row.get("activity") for row in rows)
    )
    x_full = _design_matrix(rows, with_activity)
    if np.linalg.matrix_rank(x_full) < x_full.shape[1]:
        return _unidentifiable("tobit", len(rows), "设计矩阵秩不足，价格与活动完全重叠或价格无变化", len(censored_rows))
    y = np.array([float(row["units"]) for row in rows])
    censor = np.array([bool(row.get("stockout")) for row in rows])
    # 用完整观测上的 OLS 初值，降低小样本下的优化敏感性
    ols = fit_ols(rows, with_activity) if len(complete) >= x_full.shape[1] else None
    if ols is not None and ols.identified:
        start = [ols.intercept, ols.price_coef]
        if with_activity:
            start.append(ols.activity_coef)
        start.append(np.log(max(ols.sigma or 1.0, 1e-3)))
    else:
        start = [float(np.mean(y)), 0.0] + ([0.0] if with_activity else []) + [0.0]
    result = optimize.minimize(
        _tobit_neg_log_likelihood,
        np.array(start, dtype=float),
        args=(x_full, y, censor),
        method="BFGS",
    )
    if not result.success:
        failed = Fit(
            name="tobit",
            identified=False,
            price_coef=None,
            n_used=len(rows),
            n_censored=len(censored_rows),
            converged=False,
            reason=f"极大似然未收敛: {result.message}",
        )
        return failed
    beta = result.x[:-1]
    sigma = float(np.exp(result.x[-1]))
    # BFGS 的逆 Hessian 近似参数协方差；非正定则不报告标准误
    hess_inv = result.hess_inv
    cov = None
    try:
        cov = np.asarray(hess_inv, dtype=float)
        if cov.shape != (len(result.x), len(result.x)) or np.any(np.diag(cov) <= 0):
            cov = None
    except (TypeError, ValueError):
        cov = None
    se = np.sqrt(np.diag(cov)) if cov is not None else np.full(len(result.x), np.nan)
    return Fit(
        name="tobit",
        identified=True,
        intercept=float(beta[0]),
        price_coef=float(beta[1]),
        activity_coef=float(beta[2]) if with_activity else None,
        price_se=None if np.isnan(se[1]) else float(se[1]),
        activity_se=None if with_activity and np.isnan(se[2]) else (float(se[2]) if with_activity else None),
        sigma=sigma,
        n_used=len(rows),
        n_censored=len(censored_rows),
        diagnostics={"parameter_cov": cov if cov is not None else np.full((len(result.x), len(result.x)), np.nan),
                     "log_likelihood": -float(result.fun)},
    )


def candidate_fits(rows: list[dict]) -> list[Fit]:
    """同一批观测上的可比较模型设定，按固定顺序返回。"""
    return [fit_ols(rows, with_activity=False), fit_ols(rows, with_activity=True), fit_tobit(rows)]


def slope(rows: list[dict]) -> float | None:
    """历史兼容：未截断观测上的纯价格 OLS 斜率。"""
    fit = fit_ols(rows, with_activity=False)
    return fit.price_coef
