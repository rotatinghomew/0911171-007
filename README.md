# 价格响应分析

容器环境固定在仓库 Dockerfile 的 Python 3.11.14 镜像摘要，数值分析依赖与传递依赖在 requirements.txt 中精确锁定。执行 `docker build -t local-analytics .` 后，`docker run --rm --network none local-analytics` 运行内置例子；`docker run --rm --network none local-analytics python -m unittest discover -s tests -v` 运行测试。构建时安装依赖，运行时无需联网；非容器环境使用 Python 3.11，并先执行 `python -m pip install -r requirements.txt`。

这是面向商品经营分析的合成数据原型，包含观测整理、多设定价格响应估计、采购前可审阅的需求依据和补货情景，不依赖外部服务。

运行 `python -m unittest discover -s tests -v`；运行 `python -m pricing.demo`。销量与价格的关联不自动构成因果结论，样例只用于本地流程验证。

## 观测与模型设定

`pricing.observations` 按门店商品保留每期价格、活动指示、可售库存与观测期间。缺货行是**右截断观测**（真实需求不低于当期可售库存），不再被当作低需求丢弃：`select_groups` 保留全部观测并按期间排序，`eligible`/`by_store_product` 仍只返回完整观测，供只使用非截断数据的设定使用。

`pricing.estimate` 在同一批观测上拟合三种可比较设定（`candidate_fits`）：

- `ols_price`：仅价格的 OLS，只用未截断观测；
- `ols_activity`：价格 + 活动指示的 OLS，只用未截断观测；
- `tobit`：右截断正态极大似然，缺货行以可售库存为截断点参与估计。

每个设定都报告价格系数与标准误、残差尺度和预测区间。设计矩阵秩不足（价格无变化、价格与活动完全重叠）时返回 `identified=False` 并给出原因，不会硬算弹性；恰好可拟合但无残差自由度时系数仍可识别，只是不确定性不可估。

## 采购前的需求依据与人工决定

`pricing.planning.demand_basis` 为每个门店商品产出可审阅证据包：观测窗口、各设定结果、推荐设定（有截断时优先 Tobit，其次控制活动的 OLS）、点预测、预测区间、弹性与显式标记。以下情形标记为 `status="manual"`，**不给定量需求（不填零、不用全店平均遮盖）**，原因写入 `manual_reasons`：

- `price_activity_overlap`：价格与活动完全重叠，弹性不可识别；
- `outside_historical_price_range`：拟用零售价超出历史价格支持范围，属于外推；
- `specification_sensitive`：设定间价格系数相对离散超过 `SENSITIVITY_REL`；
- `weak_evidence`：系数相对标准误或预测区间相对宽度超过阈值，估计不足。

`censored_demand`、`few_observations` 是信息性标记，随证据保留但不单独阻断定量。旧接口 `scenarios` 保留，人工项的 `expected_units` 为 `None`。

## 报价、在途与共享预算

`pricing.purchasing.PurchaseDesk.quote` 在给定零售价、补货周期（`cycle_periods`）、现货、箱规和共享预算下生成整箱报价：先扣除现货与到货期限内（`arrives_cutoff`）的在途，再按 `pack_size` 向上取整。传入 `Stockroom` 时，已确认在途占用的预算（`committed_cost`）从共享预算扣除，报价返回 `committed_cost`、`remaining_budget` 与 `within_budget`。反复报价和 `compare_options` 都是只读的，不会重复占用在途或预算。

含人工项的报价 `complete=False`，不能确认。`approve` 沿用既有确认入口并扩展为：

1. 以台账当前口径复核已用预算，口径漂移或超预算即拒绝；
2. 按订单行幂等登记在途（单号 `订单号:门店:商品`），写入对应预算占用；
3. 冻结当次采用的证据与方案（含观测窗口、模型设定、不确定性），之后换模型/换价格产生的是新报价，不能改写已确认采购；同一订单号重试确认直接返回冻结副本，不会再登记一遍在途或再加一次预算。

`pricing.stockroom.Stockroom` 的到货仍只把在途转入现货一次，`committed_cost()` 汇总的已占用预算不因到货消失，因此确认后采购、在途与剩余预算彼此一致。供货条款中的 `unit_cost` 是采购单价，不能与零售价格混用。

## 测试

- `tests/test_demand_models.py`：截断观测处理、Tobit 识别与不确定性、活动重叠不可识别、小样本精确拟合；
- `tests/test_demand_basis.py`：证据包、外推/重叠/敏感/弱证据的人工决定、旧接口语义；
- `tests/test_purchase_flow.py`：在途合并与预算扣除、方案比较只读、确认幂等、证据绑定与不改写、口径漂移拦截、数量可回溯到证据与箱规；
- `tests/test_stockroom.py`、`tests/test_purchasing.py`、`tests/test_pricing.py`：既有行为的回归保护。
