# NL2SQL 查询安全沙箱与自愈纠错技术设计

更新：2026-10-15。本文档说明基于大语言模型自然语言生成 SQL（NL2SQL）过程中的“语法树 AST 深度安全沙箱”、“只读访问控制”、“多级行数截断”以及“运行时错误自愈纠错循环”的技术架构与安全防护规范。

## 1. 安全背景与防护目标

让大模型直接生成并在企业数据库上执行 SQL 查询具备极高灵活性，但也引入了巨大的安全风险（如 SQL 注入、越权访问系统表、非预期的写操作/DDL、恶意耗尽内存的海量结果集等）。
- **零写入绝对只读**：在 AST 抽象语法树层面物理阻断任何写操作与结构破坏操作。
- **视图与模式强隔离**：严格限定查询仅能引用系统白名单授权的业务视图，禁止跨模式访问系统字典（如 `pg_*`、`information_schema`）。
- **函数与操作白名单**：通过严密的语法函数白名单，阻止危险的数据库特权函数、文件系统访问函数或无界类型转换。
- **内存熔断与上下文保护**：数据库端强制限定返回上限 200 行；回传大模型可见上下文二次截断为 20 行，防止长表格挤占上下文。
- **错误自愈重试循环（Self-Correction Loop）**：当遇到字段名拼写错误、类型转换不匹配或聚合遗漏时，以结构化错误反馈引导模型自动纠错，提升问答完成率。

## 2. 总体沙箱流水线

```text
[ LLM 生成候选 SQL 语句 ]
           │
           ▼
[ 1. 语法树解析与方言适配 (sqlglot) ]
   ├─ 长度校验: len(sql) <= 20000 字符
   └─ 单条语句校验: 仅支持单条 exp.Select / exp.Union 等
           │
           ▼
[ 2. 深度 AST 节点白名单审计 (app/analytics/sql_policy.py) ]
   ├─ 阻断写节点: Insert, Update, Delete, Create, Drop, Lock, Set 等
   ├─ 检查函数白名单: 必须属于 SAFE_FUNCTIONS (如 SUM, AVG, DATE_TRUNC)
   ├─ 校验 Cast 目标类型: 仅限 TEXT, VARCHAR, BIGINT, DATE, DOUBLE 等
   └─ 视图引用解析: 校验每个引用表是否属于 allowed_views
           │
           ▼ (沙箱校验通过)
[ 3. 执行器执行与结果截断 (app/agents/tools.py) ]
   ├─ 数据库物理执行: 强制带上限 (最多 200 行)
   ├─ 结果归档: 完整数据写入证据库并分配证据 ID (如 "T8a4f...")
   └─ 模型视图绑定: 仅返回前 20 行样本 (model_rows_truncated=true)
           │
           ├─ 执行成功 ──> 返回查询结果与图表配置
           └─ 执行报错 ──> 捕获原生 DB 错误，进入 [4. 错误自愈提示]
```

## 3. AST 安全沙箱核心实现（app/analytics/sql_policy.py）

系统基于 `sqlglot` 构建针对 PostgreSQL、DuckDB 及 SQLite 的严格校验机制：

### 3.1 语句类型与节点白名单

```python
# 1. 严格禁止任何写与模式更改节点
forbidden = (
    exp.Insert, exp.Update, exp.Delete, exp.Create, 
    exp.Drop, exp.Command, exp.Into, exp.Lock, exp.Set
)
if any(isinstance(node, forbidden) for node in tree.walk()):
    raise ValueError('查询包含禁止的写入或锁定操作')
```

### 3.2 函数白名单体系（SAFE_FUNCTIONS）

仅放行标准、安全的分析计算与时间处理函数，杜绝任何外部函数调用：
```python
SAFE_FUNCTIONS = {
    'SUM', 'AVG', 'MIN', 'MAX', 'COUNT', 'COALESCE', 'NULLIF', 'ROUND', 'ABS',
    'LOWER', 'UPPER', 'LENGTH', 'TRIM', 'SUBSTRING', 'DATE_TRUNC', 'EXTRACT',
    'CURRENT_DATE', 'CURRENT_TIMESTAMP', 'CAST', 'CASE', 'IF', 'ROW_NUMBER',
    'AND', 'OR', 'TIMESTAMP_TRUNC', 'RANK', 'DENSE_RANK', 'LAG', 'LEAD',
    'FIRST_VALUE', 'LAST_VALUE', 'GREATEST', 'LEAST', 'CONCAT', 'TO_CHAR',
    'POWER', 'FLOOR', 'CEIL', 'PERCENTILE_CONT', 'PERCENTILE_DISC', 'WITHIN_GROUP'
}
```
凡不在白名单内的函数，或通过属性点号调用的对象级方法（如 `schema.custom_func()`），均直接抛出“不允许的函数”并拒绝执行。

### 3.3 授权视图边界限定（Relation Resolution）

通过 `traverse_scope(tree)` 遍历 SQL 的查询作用域：
- 提取所有的基础数据表/视图名。
- 逐一与数据源登记的 `allowed_views` 白名单比对。
- 若 SQL 尝试访问未授权的数据表或系统模式表（如 `pg_catalog.pg_user`），立即拦截并报错。

## 4. 多级数据截断与内存熔断

在 `app/agents/tools.py` 的 `SQLTools.tool` 装饰器中执行双重保护：

| 保护层级 | 阈值规则 | 实现手段 | 目的 |
| :--- | :--- | :--- | :--- |
| **底层数据库执行层** | 最多返回 200 行 | 连接器或 SQL 引擎强制 `LIMIT 200` 约束 | 防止内存 OOM、单次大查询打满网卡 |
| **完整证据持久化层** | 完整保留（<= 200行） | 生成证据 ID（如 `T3b5...`）持久化至证据库 | 保证人工复核、报表导出具备完整精确数据 |
| **大模型推理上下文层** | **最多截断至 20 行** | `evidence['rows'] = evidence['rows'][:20]` | 节约 Token 预算，保护上下文窗口 |

当行数超过 20 行时，系统打上标记：
```json
{
  "model_rows_truncated": true,
  "tool_result_id": "T8a4f91e",
  "note": "仅显示前 20 行样本；请勿基于此样本计算总和，全量汇总请执行聚合 SQL。"
}
```
在系统提示词中强制约束模型：“当 `model_rows_truncated=true` 时，不得从样本计算全量指标，应补充聚合查询”。

## 5. 错误捕获与动态自愈循环（Self-Correction）

### 5.1 错误分类与反馈设计

当 SQL 触发沙箱拒绝或数据库报错时，系统不中断 Agent 运行，而是将其转化为结构化工具错误回传：
- **语法错误**：`{"code": "SQL_SYNTAX_ERROR", "error": "第1行第15列附近存在语法错误，请检查关键字拼写。"}`
- **字段不存在**：`{"code": "COLUMN_NOT_FOUND", "error": "列 'amt' 不存在；当前视图可选列为: 'amount', 'customer_name'..."}`
- **聚合错误**：`{"code": "GROUP_BY_MISSING", "error": "列 'region' 必须出现在 GROUP BY 子句中或在聚合函数中使用。"}`

### 5.2 自愈收敛控制

Agent 接收到具体的数据库错误后，利用前述的 `ExecutionControl` 中间件与错误反馈，启动自愈步骤：
1. 模型读取错误提示中的正确列名或聚合建议。
2. 调整 SQL 并在下一轮工具调用中执行修复后的 SQL。
3. 若由于不可恢复的原因连续尝试相同错误参数，触发前述指纹去重（`REPEATED_TOOL_CALL`），平滑退化至说明限制并给出友好提示。
