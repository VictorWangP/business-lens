# Text2SQL 与关系数据库 Agent 查询设计

> 基于 2026-10-12 工作区源码梳理。本文中的“当前实现”描述已存在的行为；“建议方案”是后续开发参考，尚未实现。分析依据为仓库代码，未连接业务数据库或调用真实模型。

## 1. 目标与设计结论

当前 Text2SQL 已融入统一业务分析 Agent：模型根据问题选择指标工具、SQL 工具与知识检索工具，通过多轮调用获取证据后回答。没有独立的自然语言转 SQL HTTP 接口，也没有单独的 SQL 生成服务；SQL 由支持工具调用的对话模型作为 `execute_readonly_sql` 的参数生成。

建议保留单 Agent 与现有 Connector 边界，将关系数据库查询逐步加强为“授权资源 → 语义上下文 → 查询计划 → SQL 校验 → 受控执行 → 证据回答”。由模型负责理解问题和选择工具，由服务端负责权限、状态约束、预算和结果契约。常用统计优先使用版本化指标；探索查询仅访问明确授权的业务视图。

本文覆盖关系数据库接入、Agent 查询、SQL 防护、结果与审计、后续模块设计和验收要求。后台运行、多会话并发和 SSE 续接方案见 [Agent 后台执行与多会话并发设计](agent_background_execution_design.md)。向量检索实现见 [向量服务设计](vector_service_design.md)，总体分层见 [架构说明](architecture.md)，经营分析示例见 [业务数据字典](business_dataset_dictionary.md)。纯 SQL 问数不依赖嵌入模型。

## 2. 当前代码地图

以下路径相对于仓库根目录。

| 入口 | 当前职责 |
| --- | --- |
| `backend/app/api/chat.py` | `POST /api/chat/stream`，身份认证与 SSE 响应 |
| `backend/app/schemas/chat.py` | `ChatRequest`，问题、会话、模型和业务空间绑定；不接受来源覆盖 |
| `backend/app/application/chat.py` | `prepare_chat` 校验资源并创建运行；`stream_chat` 保存事件、答案与状态 |
| `backend/app/agents/executor.py` | `AgentExecutor`，六个工具、FunctionAgent 循环、预算、查询证据及引用检查 |
| `backend/app/api/data_sources.py` | 数据源 CRUD、连通性测试、手工 SQL、指标管理、文件导入 |
| `backend/app/connectors/registry.py` | 按数据源类型派发检查和执行，转换 SQL 方言名称 |
| `backend/app/connectors/postgres.py` | PostgreSQL 只读连接、角色检查、授权视图元数据、查询执行 |
| `backend/app/connectors/local.py` | 私有 DuckDB / SQLite 文件路径检查、只读查询与超时 |
| `backend/app/analytics/sql_policy.py` | SQLGlot AST 策略、关系白名单、函数与类型限制、外层 LIMIT |
| `backend/app/analytics/presentation.py` | Decimal 等值的 JSON 转换、真实行集驱动图表与指标卡片 |
| `backend/app/models/platform.py` | `DataSource`、`MetricDefinition`、`AgentRun`、`RunEvent` |
| `backend/app/api/runs.py` | 当前用户运行列表和按序事件查询 |
| `backend/app/infrastructure/credentials.py` | Fernet 凭据加密与解密 |

注意：`__pycache__` 中可能存在旧 `sql_analytics` 编译产物，不应将其视为当前源码入口。

## 3. 当前端到端流程

### 3.1 数据源准备

1. PostgreSQL 通过 `POST /api/data-sources` 保存名称、连接 URL、业务 schema 和 `allowed_views`。URL 加密后入库，公开响应不包含连接凭据。创建阶段校验 URL 格式，不会立即检查真实连接和视图。
2. `POST /api/data-sources/{id}/test` 调用真实 Connector 读取元数据，检查连接及授权对象是否可读。
3. CSV / Excel 通过 `/api/data-sources/import` 导入私有 DuckDB，注册 `main.dataset`，使用相同的 Agent 查询接口。
4. 指标通过 `POST /api/data-sources/{id}/metrics` 保存 SQL 模板。创建时执行 AST 校验，要求占位符集合恰好为 `start_date`、`end_date`；不会执行 SQL 验证字段和业务口径。

当前 API 新建远程连接只支持 PostgreSQL，文件导入创建 DuckDB。Connector 虽支持 SQLite，但没有对任意 SQLite 路径开放注册接口。`storage/business_data.db` 的示例初始化脚本不会自动完成用户数据源注册，而且不满足默认的用户私有目录约束；初始化业务库与接入聊天查询是两个步骤。

### 3.2 会话准备与权限

`prepare_chat` 根据已有会话绑定或新草稿提交的 `workspace_id` 读取空间最新配置，使用服务端认证得到的 `user_id` 验证所有来源的所有权，资源不匹配返回 403。模型配置在提交时验证；Worker 启动时根据持久化的模型 ID 再从该用户的加密配置中读取凭据。已有会话也检查所有权，不能改绑空间或提交来源覆盖。

历史消息仅读取当前空间配置版本下最近 12 条 user / assistant 正文，再按总计 24,000 字符裁剪。随后读取用户偏好，并与问题一起保存为 `AgentRun.input_payload` 快照；保存用户消息、助手占位消息和运行记录后提交到数据库队列。历史工具调用和行集不会作为工具历史重新注入；后续提问需要重新查询，不能将历史回答数字当成当前事实。执行记录中的空间版本及来源快照决定本次工具访问范围，执行开始后的配置变更从下一次请求生效。长期记忆仅使用用户画像与偏好，不注入跨范围的业务事实。同一会话有 queued / running / cancel_requested 任务时拒绝新问题，不同会话可并发。

### 3.3 模型与工具循环

后台 Worker 读取固定的输入与资源快照后，`AgentExecutor.stream` 构造 `OpenAILike` 和 LlamaIndex `FunctionAgent`，使用执行时用户模型配置、提交时历史和用户偏好。系统提示要求先查看资源，优先使用业务指标，探索 SQL 前查看 Schema，区分事实与推断。当前日期按 Asia/Shanghai 注入。

| 工具 | 输入 | 输出或行为 |
| --- | --- | --- |
| `list_available_resources` | 无 | 所选知识库 ID、数据源 id/name/kind/description、指标 id/name/description/unit |
| `get_business_schema` | `source_id` | source_id、schema、dialect、授权对象的 table_name/column_name/data_type |
| `query_metrics` | `metric_id`、开始和结束日期字符串 | 验证日期及授权，绑定模板参数，返回结果和指标名称、定义、单位 |
| `execute_readonly_sql` | `source_id`、`sql` | 校验授权并执行 SQL，返回证据结果 |
| `search_knowledge` | query、top_k | 文档证据，用于业务政策或解释依据 |
| `read_document_section` | chunk_id | 命中原文及相邻切片 |

模型可组合 SQL 与文档查询，也可在出错后改写 SQL。工具包装器将异常作为错误工具结果交还模型；目前没有独立的 SQL 修复工作流或按错误类型细分的修复次数。`get_business_schema` 的先调用要求只由提示词和工具描述表达，服务端尚未强制。

默认 `allow_parallel_tool_calls=False`，调用顺序由 Agent 决定。当前不是固定“生成一次 SQL → 执行一次 → 回答”的流水线。

### 3.4 SQL 校验与执行

`execute_readonly_sql → source → query → registry.execute → Connector.execute → validate_sql → 数据库`。

Agent 每次取数据源时同时检查它在本次 `source_ids` 内且属于当前用户。指标按 metric 所有者和已选数据源范围查询，再加载其数据源。手工 `/query` API 不经过 Agent，但复用 Connector 和 SQL 策略，避免绕过底层校验。

`validate_sql` 的实际规则：

- SQL 长度最多 20,000 字符，schema 符合受限标识符格式。
- 只接受单条 SELECT 或 UNION / INTERSECT / EXCEPT 查询；拒绝写入、建表、锁定等 AST 节点，包括 CTE 中的写入。
- 按 SQL 作用域遍历底层关系，区分 CTE / 子查询与真实对象；所有真实对象必须属于指定 schema 和白名单，拒绝 catalog、其他 schema 和未授权关系。
- 将底层对象重写为带双引号的指定 schema 和对象名，避免 search_path 影响。
- 函数采用白名单，拒绝未知函数及带命名空间的函数；限制 CAST 类型。
- 拒绝不支持的 SQL 参数节点，参数生成器仅支持 start_date / end_date。探索工具没有独立 params 入参，日期通常由模型写为 SQL 字面量。
- 至少读取一个授权关系，`SELECT 1` 不能作为业务查询。
- 外包 `SELECT * FROM (...) AS business_result LIMIT SQL_MAX_ROWS + 1`，用于识别超量结果。

当前没有依据真实 Schema 校验列、JOIN 键和聚合口径；字段错误通常由数据库发现。LIMIT 限制返回行数，不限制扫描量或 JOIN 的计算量。

### 3.5 PostgreSQL 的数据库侧约束

每次 Schema 检查或执行都创建独立异步 engine（pool_size=1、max_overflow=0），结束后 dispose；不是跨请求复用连接池。连接超时 10 秒，命令超时来自 SQL 配置。

连接进入事务后设置 READ ONLY、statement_timeout 和 `search_path=pg_catalog`，随后检查当前角色的 superuser、bypassrls、createrole、createdb 标志，以及 `information_schema.table_privileges` 中当前用户名的写权限。逐个检查 `allowed_views` 必须是普通视图且不由当前角色拥有。Schema 查询返回真实可见视图字段，并确认所有授权视图都找到。

这些检查不能单独证明全部有效权限都安全：继承角色、PUBLIC 授权、视图所有者执行语义及底表 RLS 需要数据库部署侧审查。当前没有将应用 `user_id` 绑定到数据库租户上下文；应用的数据源所有权隔离不等同于业务行级隔离。共用业务账号时，应预先通过数据库角色、受限视图或经验证的 RLS 实现业务授权。

### 3.6 本地文件数据源

路径解密后必须位于 `USER_STORAGE_DIR/{user_id}/data_sources` 内且文件存在。DuckDB 以只读模式运行，禁用外部访问和扩展自动安装/加载，限制线程为 2、内存为 256MB，用定时 interrupt 控制超时。SQLite 使用 mode=ro、query_only 和进度回调超时。执行放入线程，避免阻塞异步事件循环。

本地执行拒绝结果重复列名；PostgreSQL 路径没有对应的显式检测，后续应统一。不同数据源的本地文件、远程连接相互隔离，当前不支持跨数据源 SQL JOIN。

### 3.7 查询证据、展示与持久化

成功执行生成 UUID `query_id` 与本次运行内递增 `citation_id=Q1/Q2/...`。结果包含 rows、truncated、重写后的 sql、source_id/name、retrieved_at、parameters。`retrieved_at` 是查询返回后的应用时间，不是业务数据更新时间，也不是查询耗时。

Decimal 和超出 JavaScript 安全整数范围的整数以字符串传输，日期用 ISO 字符串。图表在转换前从真实结果生成：行数不超过 50、包含分类与数值列时尝试生成；单行数值可生成卡片。截断结果不会生成图表或卡片。图表数值转 float，仅用于展示，精确金额以查询行集为准。中文问题中“饼图/环形图”选 pie，“折线/趋势图”选 line，否则 bar；这是展示选择规则。

SSE 事件包含 run_started、status、tool_start、tool_end、query_result、可选 tool_call（图表/卡片）、citations、usage、chunk、error、done。后台 Worker 为每条事件分配 run_id、sequence、trace_id 并保存至 RunEvent，同时更新助手占位消息的进度投影。SSE 接口仅读取事件日志；页面断开或切换会话不会取消任务。重新订阅使用 `after_sequence` 补齐事件。中间 AgentStream 不作为正文发送，最终答案校验后一次输出 chunk。

最终只检查答案中的 `[查询 Qn]` 和 `[来源 Sn]` 是否存在；不检查每个数字是否被引用，也不判断语义是否与证据一致。查询结果仍可能为空、口径错误或不能支持结论。

运行状态包括 queued、running、cancel_requested、completed、partial、failed、cancelled。工具发生错误后即使模型恢复并回答，通常仍为 partial；预算异常使运行失败。只有带用户鉴权的取消接口会请求停止指定 run，Worker 检查取消标记并取消 LlamaIndex handler；浏览器连接断开不会取消任务。助手消息保存所有 query_results，图表/卡片只保留最后一次 tool_call 的展示数据；完整事件仍可查询。

## 4. 当前配置与风险边界

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `AGENT_MAX_STEPS` | 12 | Agent 迭代上限 |
| `AGENT_MAX_TOOL_CALLS` | 16 | 工具调用上限 |
| `AGENT_TIMEOUT` | 180 秒 | 工作流与外层执行时间预算 |
| `AGENT_WORKER_CONCURRENCY` | 5 | 默认数据库 Worker / Celery Worker 的 Agent 并发上限 |
| `AGENT_MAX_TOTAL_TOKENS` | 64,000 | TokenCountingHandler 估算预算，不等同供应商计费统计 |
| `SQL_TIMEOUT_MS` | 15,000 毫秒 | 数据库命令或本地执行超时 |
| `SQL_MAX_ROWS` | 200 | 最多返回 200 行，多取一行识别截断 |

相同工具名与参数指纹允许执行两次，第三次返回重复调用错误。模型请求固定 timeout=60、max_retries=1、max_tokens=4096、context_window=32768；这些参数当前写在 executor 中，后续应按模型能力配置。完整行集进入工具上下文，长文本和宽表可能先耗尽上下文。

错误输出对非 ValueError 使用通用描述，避免暴露数据库或供应商原始响应；ValueError 消息目前直接交给模型，新增异常时仍需审查内容。工具参数、SQL、查询结果会进入事件存储，现有审计能力还缺少敏感列脱敏、字节预算和保留期管理。

## 5. 建议的关系数据库查询架构（待实现）

### 5.1 模块分工

保留现有入口和工具名，渐进提取 executor 内部职责，避免先引入多个 Agent 或重写全部链路。

| 建议模块 | 职责 | 复用与迁移 |
| --- | --- | --- |
| `application/business_query.py` | 统一查询用例：授权、上下文版本、策略、执行、证据 | Agent、手工查询和指标共用；先迁移 `AgentExecutor.query` 的执行部分 |
| `analytics/schema_catalog.py` | 授权对象、字段注释、类型、粒度、关系、更新时间 | 在 Connector.inspect_source 之上构建，缓存按权限和版本隔离 |
| `analytics/query_plan.py` | 结构化问题计划与语义检查 | 明确指标、维度、时间、筛选、排序、连接与输出需求 |
| `analytics/sql_policy.py` | 确定性 AST 校验与重写 | 保留当前唯一底层 SQL 安全入口，增补列和参数检查 |
| `analytics/query_errors.py` | 标准错误码、可修复信息与重试分类 | Connector 异常转为脱敏的业务错误 |
| `schemas/business_query.py` | 查询请求、结果、列元数据和警告契约 | 统一 Connector、SSE 与存储之间的边界 |
| `connectors/*` | 方言、只读事务、超时、执行与取消 | 新数据库通过适配器接入 |

### 5.2 语义目录与问题计划

仅有字段名和类型难以解决“收入/回款/签约”“万元/元”“年累计/全年”等差异。建议对授权视图维护：业务描述、字段别名和注释、单位、时间语义、数据粒度、主键/唯一键、可用 JOIN 及其基数、敏感等级、数据覆盖区间与真实更新来源。视图关系不能假定可从数据库外键自动推导，应允许人工审核配置。

目录最小形式可采用独立的 `SourceSchemaSnapshot` 与人工维护的语义覆盖配置；新增持久表使用 Alembic。每个快照记录 source_id、授权范围指纹、schema_version、采集时间。缓存键包含用户/授权范围与版本，数据源更新或权限变化使缓存失效；执行时仍检查当前授权，缓存不能授予权限。

建议的 QueryPlan（内部对象，不直接执行用户自由输入）：

```json
{
  "source_id": "<selected-source-id>",
  "schema_version": "<snapshot-version>",
  "metric": "revenue",
  "dimensions": ["region"],
  "time_range": {"start": "2026-01-01", "end_exclusive": "2026-02-01"},
  "filters": [],
  "unit": "CNY",
  "grain": "region/month",
  "order_by": [{"field": "revenue", "direction": "desc"}],
  "limit": 10,
  "assumptions": []
}
```

该对象是设计示例，不是当前 API。口径不唯一且影响结果时先澄清；不应以“更像用户想要的”方式悄悄更换指标。年度问题应同时展示数据覆盖期间，不能用当前日期推断数据库已更新到当天。

### 5.3 强制查询状态与有限修复

建议服务端维护每个运行、每个 source 的 Schema 已读取版本。探索 SQL 未读取 Schema 或版本失效时返回 `SCHEMA_REQUIRED`；指标模板有独立版本与验证状态，可以使用其已验证上下文。状态不能只依赖模型是否声称已经看过 Schema。

执行顺序：授权检查 → 获取有效 Schema → 计划检查 → 生成 SQL/绑定参数 → AST 与字段校验 → 可选成本检查 → 只读执行 → 结果校验 → 持久化证据 → 合成回答。所有入口均走共享执行用例；直接 SQL API 可由服务端获取 Schema，不必要求人工模拟 Agent 调用。

| 错误类别（建议） | 处理 |
| --- | --- |
| `SCHEMA_REQUIRED` / `SCHEMA_STALE` | 读取或刷新一次 Schema，再重新规划 |
| `SQL_SYNTAX` / `COLUMN_NOT_FOUND` | 返回脱敏错误及允许字段；最多修复两次，并消耗总工具预算 |
| `POLICY_DENIED` / `SOURCE_FORBIDDEN` | 当前候选失败；禁止放宽授权、函数白名单或切换更高权限账号 |
| `QUERY_TIMEOUT` / `QUERY_TOO_EXPENSIVE` | 缩小范围或改聚合一次，明确告知范围变化；不重复原 SQL |
| `CONNECTION_FAILED` | 返回可操作提示；仅在剩余预算允许时有限重试 |
| 空结果 | 成功结果，说明过滤范围；不能自动删除条件来凑结果 |
| 截断结果 | 保留警告，需要全量统计时在数据库端执行聚合 |

修复总次数受独立 SQL 预算与现有 Agent 总预算双重约束。指纹建议包含规范化 SQL AST、绑定参数和 source_id，避免只改空格绕过重复控制。记录每次候选、失败类别与后继尝试的关联，但不给模型原始凭据或内部堆栈。

### 5.4 参数、指标与 JOIN

探索 SQL 建议增加受限 `parameters`，在应用层验证名称、类型、数量和长度后由驱动绑定，SQL 标识符仍通过白名单与 AST 处理。占位符策略应随 Connector 显式适配，不能对模型输出做字符串替换。

指标建议增加 version、状态（draft/validated/published）、时间粒度、单位、维度、口径说明和验证记录。发布前执行参数绑定、字段解析与专用测试库样例校验。修改授权范围时重新验证受影响指标；历史证据保存当时版本。日期保持开始包含、结束不包含。比率统一处理分母为零，缺失同期数据不按零计算，同比增长必须比较相同覆盖期间。

JOIN 优先使用已审核关系；先确认每个视图粒度，再决定先聚合还是连接。事实表直接多对多连接会放大金额，即使 SQL 合法也不能直接认定正确。未经审核的关系进入澄清或人工配置流程。跨数据源查询继续分开执行并标明口径；真正的联邦查询作为单独功能设计。

### 5.5 数据库防护与性能

- PostgreSQL 使用专用非所有者只读角色，仅授予业务 schema USAGE 和授权视图 SELECT。验证继承权限、PUBLIC 权限、视图和底表 RLS 的实际结果；需要租户隔离时，由服务端提供可信租户上下文并在数据库侧落实。不得依赖模型生成 tenant_id 条件。
- 大型查询可选先做不带 ANALYZE 的 EXPLAIN，再按估算扫描量、连接数或成本拒绝；估算值用于预警，不能取代执行超时。EXPLAIN 仅作用于已通过策略的查询。
- 连接池按 source 和凭据版本管理，设置全局/用户/数据源并发上限、等待超时和闲置淘汰。不能为每个 source 无限保留 engine。凭据轮换使旧池失效。
- 建立明确取消机制，将 Agent 取消传递到数据库任务。本地 `to_thread` 的取消不保证立即停止底层线程，仍需 interrupt/进度回调兜底；验证远程驱动的真实取消行为。
- 增加返回字节数、单元格长度与 LLM 上下文预算。证据存储和给模型的摘要分离，摘要必须携带截断/采样标志，不能代替完整结果冒充全量。
- 函数白名单和新方言扩展需伴随拒绝测试，不能为修复单条 SQL 开放任意函数、外部文件或网络读取。

## 6. 建议结果契约与审计（待实现）

在保留现有字段基础上扩展 `QueryEvidence`：

| 字段 | 含义 |
| --- | --- |
| query_id / run_id / citation_id | 全局查询、运行与运行内引用标识；Q1 不能脱离 run_id 使用 |
| source_id / schema_version / metric_version | 授权来源和查询时上下文版本 |
| original_sql / executed_sql / parameters | 原始候选、策略重写 SQL、脱敏后的绑定参数 |
| columns | 名称、数据库类型、单位、精度、敏感等级，拒绝重复名称 |
| rows / returned_row_count / truncated | 实际返回行集、返回条数与上限截断标志；不伪称总行数 |
| started_at / finished_at / duration_ms | 明确执行时点与耗时 |
| data_as_of / coverage | 来自真实元数据的更新时间和覆盖范围，未知则留空 |
| warnings / status / error_code | 空结果、覆盖不足、截断、异常等机器可读信息 |

对 Decimal 与大整数保持现有字符串约定。图表应关联 query_id，多个查询分别保存图表，避免只显示最后一张。正文引用检查继续保留，再逐步增加“关键数字有查询支持、单位一致、不得对截断行集求全量”的校验；不能将引用存在检查描述为事实准确性验证。

敏感列在送往模型、SSE 和持久化前按策略处理，优先在授权视图中剔除或脱敏。运行记录设置保留期与访问审计。观测记录耗时、扫描/返回规模、错误码和预算用量；禁止日志记录明文连接串、密码和供应商密钥。trace_id 只用于关联，不能替代用户授权。

## 7. 参考场景

### 7.1 既定指标：一月销售额

当前流程：列资源找到指标 → `query_metrics(metric_id, '2026-01-01', '2026-02-01')` → 日期对象绑定模板 → 同样的 SQL 策略与数据库只读执行 → 返回 Q1 → 引用 `[查询 Q1]` 回答，并说明单位。

未来加入：指标发布版本、数据覆盖与执行耗时。模型无需为已发布口径重新生成公式。

### 7.2 探索查询：一月各区域收入前十

以下使用假设的 PostgreSQL 授权视图 `reporting.sales`；只有实际 Schema 存在这些字段才能执行。

```sql
SELECT region, SUM(amount) AS revenue
FROM sales
WHERE order_date >= DATE '2026-01-01'
  AND order_date < DATE '2026-02-01'
GROUP BY region
ORDER BY revenue DESC, region
LIMIT 10
```

当前模型先调用 get_business_schema，再把 SQL 交给 execute_readonly_sql；策略补齐 schema 并外包 LIMIT 201。前十是有意排序限制，不等同于被系统上限截断，解释时应说明是排名结果。未来计划中增加对 metric/unit/grain 的检查，并将日期改为绑定参数。

### 7.3 高风险项目与政策解释

对当前选择的风险视图执行 COUNT 和分类统计，必要时另查明细；统计查询与明细查询分别产生 Q1、Q2。检索风险管理政策产生 S1。回答区分数据库中的状态、文档中的管理规则和分析建议。

若数据只有历史快照，说明快照期间；若视图存在 `is_warned`，它只能证明数据记录的状态，不能证明 Agent 本次发送了预警。当前六个工具均不提供发送消息或更新数据库动作。

## 8. 分阶段落地与验收

| 阶段 | 实现内容 | 验收标准 |
| --- | --- | --- |
| P0：统一约束 | 提取共享查询用例、强制 Schema 前置状态、统一重复列检测与错误分类 | Agent 和手工 API 使用相同策略；跳过 Schema、越权 source、非法 SQL 均不能执行 |
| P1：业务正确性 | 语义目录、指标版本、QueryPlan、参数扩展、有限修复 | 固定业务集覆盖单位、日期边界、零分母、同期缺失、JOIN 放大与口径澄清 |
| P2：稳定性与审计 | 池化、并发与取消、字节预算、证据契约、脱敏与保留期 | 超时和断连释放资源；完整证据可关联；敏感值不进入模型或日志 |
| P3：能力扩展 | 新数据库适配器、Schema 召回、成本控制、可选联邦查询 | 每个方言通过相同契约和安全测试，不能只增加注册分支 |

建议优先在现有 PostgreSQL 路径完成 P0/P1，再增加 MySQL / SQL Server 等；当前不支持这些数据库。新适配器至少实现 inspect_source、execute、方言映射、只读事务/连接、参数绑定、超时与取消，并扩展 API 类型校验与凭据校验。

## 9. 测试基线与后续开发检查

现有测试可直接作为参考：

| 文件 | 已覆盖内容 |
| --- | --- |
| `backend/tests/test_sql_policy.py` | 写入、多语句、越权关系、危险函数、CTE、子查询、参数、外层上限 |
| `backend/tests/test_tabular.py` | 实际文件导入、本地查询、数据类型和隔离相关场景 |
| `backend/tests/test_agent.py` | 替代模型驱动真实 FunctionAgent，多工具流程、证据持久化、重复预算、图表意图 |
| `backend/tests/test_platform.py` | API 平台行为与资源权限相关场景 |
| `backend/tests/test_postgres_integration.py` | 可选真实 PostgreSQL 只读视图、Decimal、越权/写入拒绝；同文件另有向量集成测试 |
| `backend/tests/test_presentation.py` | 结果序列化及展示行为 |

在项目根目录执行确定性基线：

```bash
backend/venv/bin/python -m pytest backend/tests/test_sql_policy.py backend/tests/test_tabular.py backend/tests/test_agent.py backend/tests/test_presentation.py
```

真实 PostgreSQL SQL 路径使用专用测试库，预先安全配置 `RAG_TEST_POSTGRES_URL` 后执行：

```bash
backend/venv/bin/python -m pytest backend/tests/test_postgres_integration.py -k real_postgres_readonly
```

该测试需要管理员创建临时 schema 和 reader 角色，不能指向生产库。未配置变量会跳过。现有 MockFunctionCallingLLM 测试证明工作流契约，不证明真实模型 Text2SQL 准确率；业务脚本中的固定 SQL 校验也不证明自然语言生成能力。

后续建立版本化自然语言评测集，包含问题、允许来源、口径、预期结果和拒绝/澄清行为。分别衡量执行成功率、结果正确率、越权阻断率、澄清准确率、修复次数、延迟与 token 成本，不要求 SQL 文本完全相同。使用固定快照和固定日期比较结果，真实模型评测单独运行。

新增功能应确认：授权在服务端落实；手工 API 不能绕过策略；Schema/指标版本可追溯；日期和金额单位明确；空结果、截断和错误不隐瞒；所有业务数字来自查询证据；新增语法具有允许和拒绝测试；数据库和模型资源可以超时并释放。
