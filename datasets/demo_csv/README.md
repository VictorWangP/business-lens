# CSV 模拟业务数据集与演示指南

共 **20 个 CSV、162,366 行**。UTF-8 BOM 编码，首行为英文列名，分类值主要使用中文。所有数据均为模拟演示数据；`reference_*` 是已有 `storage/business_data.db` 演示视图的原样导出，不代表实际企业经营数据。

新增模拟数据的实际日期范围为 **2024-01-01 至 2026-10-09**，固定随机种子 `20261010`。2026 年 10 月为月内快照，11/12 月尚未发生；商机预计成交和项目计划日期可以晚于快照日。

## 建议先导入这三份

- `03_monthly_sales.csv`：月度收入与毛利，适合折线图。
- `10_region_sales_2026.csv`：7 个大区收入，适合柱状图和饼图。
- `12_monthly_sales_comparison.csv`：跨年双折线，2026 年尚未发生的月份保留为空。

在 UI 的“数据管理 → 业务数据”逐个导入，返回聊天后勾选相应数据集并输入下方问题。业务文件无需上传到知识库；需要已配置支持工具调用的对话模型，不需要嵌入服务。每个 CSV 独立对应一个 `dataset` 视图，演示 SQL 均为单数据源查询，当前不支持跨独立文件直接 JOIN。

图表右上角可切换柱状图、折线图、饼图。提问明确写“折线图”或“饼图”时后端会传递对应图表类型；通常每轮演示一种图表，当前回答展示最后一次生成的图表。饼图使用第一项数值指标，需要非负金额/数量且合计大于零，比例按当前查询返回的类别合计计算；Top N 饼图表示 Top N 内部占比，不等于全市场份额。

## 文件清单

| 文件 | 行数 | 大小 | 分析用途 |
| --- | ---: | ---: | --- |
| [01_sales_orders.csv](01_sales_orders.csv) | 80,000 | 20.68 MB | 销售额、毛利、同比、区域/行业/型号/渠道、退款、客户排行 |
| [02_receivables.csv](02_receivables.csv) | 30,000 | 4.99 MB | 应收、回款、账龄、逾期与客户风险；截至固定快照日期 |
| [03_monthly_sales.csv](03_monthly_sales.csv) | 1,190 | 0.13 MB | 小文件快速演示月度趋势、产品结构、区域销售和毛利率 |
| [04_unit_targets.csv](04_unit_targets.csv) | 1,054 | 0.12 MB | 目标/实绩对比、缺口、达成率、经营单元排行 |
| [05_crm_opportunities.csv](05_crm_opportunities.csv) | 24,000 | 4.09 MB | 漏斗、赢单率、渠道转化、预测管道、长期停滞商机 |
| [06_marketing_campaigns.csv](06_marketing_campaigns.csv) | 1,088 | 0.11 MB | 营销成本、获客成本、合同口径 ROAS 与渠道对比 |
| [07_project_risks.csv](07_project_risks.csv) | 6,000 | 1.14 MB | 风险项目、交付延期、回款敞口、经营单元与行业风险排行 |
| [08_inventory_snapshots.csv](08_inventory_snapshots.csv) | 17,934 | 2.15 MB | 库存趋势、库龄、滞销、库存结构；不同日期库存金额不可直接累计作为期末库存 |
| [09_daily_sales_trend.csv](09_daily_sales_trend.csv) | 1,013 | 0.05 MB | 查询最近 30 天折线图，或按月份再聚合 |
| [10_region_sales_2026.csv](10_region_sales_2026.csv) | 7 | 0.00 MB | 即导即用：7 个大区柱状图、收入份额饼图 |
| [11_product_mix_2026.csv](11_product_mix_2026.csv) | 14 | 0.00 MB | 产品排行、收入占比、销量和毛利比较 |
| [12_monthly_sales_comparison.csv](12_monthly_sales_comparison.csv) | 12 | 0.00 MB | 跨年双折线；2026 年 10 月仅至 9 日，11/12 月为空而非零 |
| [reference_01_beijing_performance.csv](reference_01_beijing_performance.csv) | 4 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |
| [reference_02_bu_target_completion_2026.csv](reference_02_bu_target_completion_2026.csv) | 12 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |
| [reference_03_commercial_market_ledger.csv](reference_03_commercial_market_ledger.csv) | 6 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |
| [reference_04_high_risk_projects.csv](reference_04_high_risk_projects.csv) | 7 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |
| [reference_05_industry_achievement_product.csv](reference_05_industry_achievement_product.csv) | 13 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |
| [reference_06_jiangxi_performance.csv](reference_06_jiangxi_performance.csv) | 3 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |
| [reference_07_ppl_contract_monthly_trend.csv](reference_07_ppl_contract_monthly_trend.csv) | 5 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |
| [reference_08_product_line_analysis.csv](reference_08_product_line_analysis.csv) | 4 | 0.00 MB | 现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对 |

## 字段与统计口径

- 所有新增金额字段后缀 `_yuan`，单位为人民币元；历史视图 `_wan` 字段单位为万元，不可混用。金额为两位十进制文本，导入后可推断为 Decimal。
- `01_sales_orders` 一行一个订单。`order_amount_yuan` 为折扣后的订单金额，`revenue_yuan` 仅在“已完成”时确认；取消/退货收入及成本为 0，退货金额另存 `refund_amount_yuan`。`gross_profit_yuan = revenue_yuan - cost_yuan`。`quantity` 是原订单数量，累计已售数量应筛选已完成订单。
- `03_monthly_sales` 和 `04_unit_targets` 的实绩由 `01` 精确汇总。目标独立模拟。整体毛利率、目标达成率使用汇总金额相除，不直接平均各行百分比。
- `02_receivables` 是 `01` 中 30,000 个已完成订单的发票子集，不覆盖全部收入。`invoice_amount_yuan = paid_amount_yuan + outstanding_amount_yuan`；逾期金额仅计入快照日已到期的未收余额。账龄桶是互斥分类。
- `05_crm_opportunities` 与销售订单独立模拟，不能将赢单合同额与确认收入混为一谈。`is_open=1` 表示尚未关闭；`weighted_pipeline_yuan` 仅计入未关闭商机。`06_marketing_campaigns` 的商机数和赢单合同额从 `05` 汇总。`win_rate_pct` 为赢单数/全部线索数，已关闭商机赢单率需另以赢单+丢单为分母。`contract_roas` 为赢单合同金额/营销投入，既不是利润 ROI，也不是确认收入回报率。
- `07_project_risks` 为独立模拟项目。按快照日和交付/回款日期计算延期天数；交付延期超过 60 天或回款逾期超过 90 天为高风险。风险等级互斥，但同一项目可同时有交付和回款风险。
- `08_inventory_snapshots` 的每个快照日覆盖全部 7 个仓库与 14 个型号；`stock_quantity = reserved_quantity + available_quantity`，`stock_value_yuan = stock_quantity × unit_cost_yuan`。期末库存只查询某一快照日，不能将不同日期库存直接相加。快照是独立模拟值，不构成可核对进销存的库存流水。
- `09` 至 `12` 均从 `01` 派生。跨年同比演示优先比较 2026 年 1—9 月与 2025 年同期；2026 年 10 月仅截至 9 日，不与完整月直接比较。
- `reference_*` 保留已有库中的预设百分比。例如政企 3000—5000 万区间的预设占比与金额比例不一致，演示饼图请按金额重算，勿直接使用 `share_in_band_pct`；本包没有修改原业务库。
- 完整列清单、行粒度、来源和 SHA-256 在 [manifest.json](manifest.json)。数值并非真实个人或企业数据，客户与项目名称均明确带“模拟”标识。

## 可复制演示问题与标准 SQL

先勾选每个问题对应的数据集。下列 SQL 可在数据源“查看数据 → 只读查询”中运行验证；聊天提问时无需粘贴 SQL。所有查询都控制在 50 行以内，适配当前图表数据限制。

### DEMO-01 · 03_monthly_sales.csv

按月份汇总销售收入和毛利，用折线图展示 2024 年至 2026 年 10 月 9 日的变化。

图表：line。

```sql
SELECT year_month, SUM(revenue_yuan) AS revenue_yuan, SUM(gross_profit_yuan) AS gross_profit_yuan FROM dataset GROUP BY year_month ORDER BY year_month;
```

### DEMO-02 · 10_region_sales_2026.csv

用柱状图比较各大区 2026 年截至快照日期的销售收入，按收入从高到低排序。

图表：bar。

```sql
SELECT region, revenue_yuan FROM dataset ORDER BY revenue_yuan DESC;
```

### DEMO-03 · 10_region_sales_2026.csv

用饼图展示各大区销售收入的占比，使用收入金额计算份额。

图表：pie。

```sql
SELECT region, revenue_yuan FROM dataset ORDER BY revenue_yuan DESC;
```

### DEMO-04 · 11_product_mix_2026.csv

用柱状图比较 2026 年销售收入最高的 10 个产品型号。

图表：bar。

```sql
SELECT model_code, revenue_yuan FROM dataset ORDER BY revenue_yuan DESC LIMIT 10;
```

### DEMO-05 · 11_product_mix_2026.csv

用饼图展示全部产品型号收入占比，不仅限于前三名。

图表：pie。

```sql
SELECT model_code, revenue_yuan FROM dataset ORDER BY revenue_yuan DESC;
```

### DEMO-06 · 12_monthly_sales_comparison.csv

使用双折线图比较 2025 年与 2026 年 1 至 9 月的每月销售收入，排除未结束的月份。

图表：line。

```sql
SELECT month_label, revenue_2025_yuan, revenue_2026_yuan FROM dataset WHERE status_2026='完整月' ORDER BY month_label;
```

### DEMO-07 · 12_monthly_sales_comparison.csv

计算 2026 年 1 至 9 月收入相对 2025 年同期的同比增长率。

图表：none。

```sql
SELECT ROUND(100.0*(SUM(revenue_2026_yuan)-SUM(revenue_2025_yuan))/NULLIF(SUM(revenue_2025_yuan),0),2) AS revenue_yoy_pct FROM dataset WHERE status_2026='完整月';
```

### DEMO-08 · 09_daily_sales_trend.csv

用折线图显示 2026 年 9 月的每日收入变化。

图表：line。

```sql
SELECT order_date,revenue_yuan FROM dataset WHERE order_date>='2026-09-01' AND order_date<'2026-10-01' ORDER BY order_date;
```

### DEMO-09 · 01_sales_orders.csv

用柱状图展示 2026 年前三季度各行业销售收入和毛利，按收入排序。

图表：bar。

```sql
SELECT industry_name,SUM(revenue_yuan) AS revenue_yuan,SUM(gross_profit_yuan) AS gross_profit_yuan FROM dataset WHERE order_date>='2026-01-01' AND order_date<'2026-10-01' GROUP BY industry_name ORDER BY revenue_yuan DESC;
```

### DEMO-10 · 01_sales_orders.csv

用饼图展示 2026 年前三季度各渠道销售收入占比。

图表：pie。

```sql
SELECT channel,SUM(revenue_yuan) AS revenue_yuan FROM dataset WHERE order_date>='2026-01-01' AND order_date<'2026-10-01' GROUP BY channel ORDER BY revenue_yuan DESC;
```

### DEMO-11 · 01_sales_orders.csv

用柱状图展示销售收入最高的前 10 个客户。

图表：bar。

```sql
SELECT customer_name,SUM(revenue_yuan) AS revenue_yuan FROM dataset GROUP BY customer_name ORDER BY revenue_yuan DESC LIMIT 10;
```

### DEMO-12 · 01_sales_orders.csv

用折线图展示每月退货订单占比，分母为当月全部订单数。

图表：line。

```sql
SELECT year_month,ROUND(100.0*SUM(CASE WHEN order_status='已退货' THEN 1 ELSE 0 END)/COUNT(*),2) AS return_order_rate_pct FROM dataset GROUP BY year_month ORDER BY year_month;
```

### DEMO-13 · 04_unit_targets.csv

用柱状图比较 2026 年 9 月收入目标与实绩，展示实绩最高的 10 个经营单元。

图表：bar。

```sql
SELECT unit_name,target_revenue_yuan,actual_revenue_yuan FROM dataset WHERE year_month='2026-09' ORDER BY actual_revenue_yuan DESC LIMIT 10;
```

### DEMO-14 · 04_unit_targets.csv

用柱状图展示 2026 年前三季度各大区整体达成率，用实绩合计除以目标合计，不平均各单元达成率。

图表：bar。

```sql
SELECT region,ROUND(100.0*SUM(actual_revenue_yuan)/NULLIF(SUM(target_revenue_yuan),0),2) AS completion_rate_pct FROM dataset WHERE year_month>='2026-01' AND year_month<'2026-10' GROUP BY region ORDER BY completion_rate_pct DESC;
```

### DEMO-15 · 02_receivables.csv

截至数据快照日期，未结清应收款的账龄结构是什么？用饼图展示。

图表：pie。

```sql
SELECT aging_bucket,SUM(outstanding_amount_yuan) AS outstanding_yuan FROM dataset WHERE outstanding_amount_yuan>0 GROUP BY aging_bucket ORDER BY outstanding_yuan DESC;
```

### DEMO-16 · 02_receivables.csv

用柱状图展示逾期应收金额最高的 10 个客户。

图表：bar。

```sql
SELECT customer_id,SUM(overdue_amount_yuan) AS overdue_yuan FROM dataset GROUP BY customer_id HAVING SUM(overdue_amount_yuan)>0 ORDER BY overdue_yuan DESC LIMIT 10;
```

### DEMO-17 · 05_crm_opportunities.csv

用柱状图展示各商机阶段数量分布。

图表：bar。

```sql
SELECT stage,COUNT(*) AS opportunity_count FROM dataset GROUP BY stage ORDER BY opportunity_count DESC;
```

### DEMO-18 · 05_crm_opportunities.csv

用柱状图比较各渠道已关闭商机的赢单率，分母为已赢单与已丢单数量之和。

图表：bar。

```sql
SELECT channel,ROUND(100.0*SUM(CASE WHEN stage='已赢单' THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),2) AS closed_win_rate_pct FROM dataset WHERE stage IN ('已赢单','已丢单') GROUP BY channel ORDER BY closed_win_rate_pct DESC;
```

### DEMO-19 · 06_marketing_campaigns.csv

用柱状图比较各渠道的获客成本，使用总投入除以总线索数。

图表：bar。

```sql
SELECT channel,ROUND(SUM(spend_yuan)/NULLIF(SUM(lead_count),0),2) AS cost_per_lead_yuan FROM dataset GROUP BY channel ORDER BY cost_per_lead_yuan ASC;
```

### DEMO-20 · 06_marketing_campaigns.csv

用折线图展示每月营销投入趋势。

图表：line。

```sql
SELECT year_month,SUM(spend_yuan) AS spend_yuan FROM dataset GROUP BY year_month ORDER BY year_month;
```

### DEMO-21 · 07_project_risks.csv

用饼图展示项目风险等级的数量占比。

图表：pie。

```sql
SELECT risk_level,COUNT(*) AS project_count FROM dataset GROUP BY risk_level ORDER BY project_count DESC;
```

### DEMO-22 · 07_project_risks.csv

用柱状图展示高风险项目未回款金额最高的 10 个经营单元。

图表：bar。

```sql
SELECT unit_name,SUM(uncollected_amount_yuan) AS uncollected_yuan FROM dataset WHERE risk_level='高风险' GROUP BY unit_name ORDER BY uncollected_yuan DESC LIMIT 10;
```

### DEMO-23 · 08_inventory_snapshots.csv

按最新快照日统计，各仓库库存金额占比如何？用饼图展示。

图表：pie。

```sql
SELECT warehouse,SUM(stock_value_yuan) AS stock_value_yuan FROM dataset WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM dataset) GROUP BY warehouse ORDER BY stock_value_yuan DESC;
```

### DEMO-24 · 08_inventory_snapshots.csv

最新快照日中各产品线滞销库存金额是多少？用柱状图展示。

图表：bar。

```sql
SELECT line_name,SUM(stock_value_yuan) AS slow_stock_value_yuan FROM dataset WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM dataset) AND is_slow_moving=1 GROUP BY line_name ORDER BY slow_stock_value_yuan DESC;
```

### DEMO-25 · reference_01_beijing_performance.csv

演示快照中北京代表处整体收入同比是多少？按两年收入合计计算。

图表：none。

```sql
SELECT ROUND(100.0*(SUM(revenue_2026_wan)-SUM(revenue_2025_wan))/SUM(revenue_2025_wan),1) AS overall_yoy_pct FROM dataset;
```

### DEMO-26 · reference_02_bu_target_completion_2026.csv

用柱状图展示演示快照中各经营单元收入，金额单位为万元。

图表：bar。

```sql
SELECT unit_name,revenue_amount_wan FROM dataset ORDER BY revenue_amount_wan DESC;
```

### DEMO-27 · reference_03_commercial_market_ledger.csv

用饼图展示演示快照中全部商业市场产品型号的销售金额占比，按金额重新计算份额。

图表：pie。

```sql
SELECT model_code,total_sales_wan FROM dataset ORDER BY total_sales_wan DESC;
```

### DEMO-28 · reference_04_high_risk_projects.csv

这个演示快照共有多少个高风险项目？

图表：none。

```sql
SELECT COUNT(*) AS high_risk_count FROM dataset;
```

### DEMO-29 · reference_05_industry_achievement_product.csv

政企行业收入在 3000 至 5000 万元的经营单元有哪些？用饼图按收入金额重新计算占比。

图表：pie。

```sql
SELECT unit_name,revenue_amount_wan FROM dataset WHERE industry_name='政企' AND revenue_amount_wan BETWEEN 3000 AND 5000 ORDER BY revenue_amount_wan DESC;
```

### DEMO-30 · reference_06_jiangxi_performance.csv

演示快照中江西办事处整体收入同比是多少？按两年收入合计计算。

图表：none。

```sql
SELECT ROUND(100.0*(SUM(revenue_2026_wan)-SUM(revenue_2025_wan))/SUM(revenue_2025_wan),1) AS overall_yoy_pct FROM dataset;
```

### DEMO-31 · reference_07_ppl_contract_monthly_trend.csv

用折线图展示演示快照中每月合同金额趋势，单位为万元。

图表：line。

```sql
SELECT sign_month,total_contract_wan FROM dataset ORDER BY sign_month;
```

### DEMO-32 · reference_08_product_line_analysis.csv

用柱状图展示演示快照中各产品线收入同比变化。

图表：bar。

```sql
SELECT line_name,yoy_change_rate_pct FROM dataset ORDER BY yoy_change_rate_pct ASC;
```

## 重新生成与验证

在项目根目录执行：

```bash
backend/venv/bin/python backend/scripts/generate_demo_csv.py
backend/venv/bin/python backend/scripts/validate_demo_csv.py
```

生成器仅只读参考原业务库，写入本目录，不创建应用数据源、不修改原应用库和业务库。重新生成会覆盖本目录中的同名 CSV 与 manifest。验证器在临时目录通过实际 CSV → DuckDB 导入器执行所有文件和示例 SQL，并核对金额及数量关系，生成 [validation_report.json](validation_report.json)。它不调用外部 LLM，不能替代真实模型的自然语言问答验收。

新增模拟数据包含季末业务量增加、2026 年智能计算订单数量下调、2026 年下半年华东订单数量下调等生成规则，便于演示异常观察。这些规则是人为设定，不能据此推断真实业务因果。
