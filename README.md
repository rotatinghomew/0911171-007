# 价格响应分析

容器环境固定在仓库 Dockerfile 的 Python 3.11.14 镜像摘要，数值分析依赖与传递依赖在 requirements.txt 中精确锁定。执行 `docker build -t local-analytics .` 后，`docker run --rm --network none local-analytics` 运行内置例子；`docker run --rm --network none local-analytics python -m unittest discover -s tests -v` 运行测试。构建时安装依赖，运行时无需联网；非容器环境使用 Python 3.11，并先执行 `python -m pip install -r requirements.txt`。

这是面向商品经营分析的合成数据原型，包含观测整理、线性响应估计和补货情景，不依赖外部服务。

运行 `python -m unittest discover -s tests -v`；运行 `python -m pricing.demo`。销量与价格的关联不自动构成因果结论，样例只用于本地流程验证。

`pricing.purchasing.PurchaseDesk` 将现有需求情景转换为整箱采购报价，先扣除门店现货，再按商品包装规格向上取整，检查采购预算后确认订单。没有需求估计的商品不能当作零需求确认；确认单独立于调用方之后对报价对象的修改。现有销量响应是各门店商品上的线性斜率，不控制活动因素；供货条款中的 `unit_cost` 是采购单价，不能与零售价格混用。

`pricing.stockroom.Stockroom` 保存现货与已确认在途单，`available_by` 将期限内预计到货合并为可用位置，可直接交给报价。到货只把在途转入现货一次，重试不重复加库存；在途单号不可换货品或数量。目前采购确认和在途登记由调用方先后执行，没有联合预算占用或自动登记。
