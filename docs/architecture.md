# 实现架构与数据契约

向量链路的配置、数据契约、实现入口、检索得分、模型迁移、索引维护与开发约束见 [向量服务设计与实现方案](vector_service_design.md)。

Text2SQL 的当前调用流程、关系数据库只读保障、查询证据契约与后续开发方案见 [Text2SQL 与关系数据库 Agent 查询设计](text2sql_agent_design.md)。

Agent 任务与 SSE 解耦、会话切换期间的后台执行、多会话并发、事件续接和取消语义见 [Agent 后台执行与多会话并发设计](agent_background_execution_design.md)。基础实现已落地；步骤级 checkpoint 恢复仍是后续能力。

## 两条真实数据链路

**结构化业务数据**：上传 CSV / Excel → 格式与数据完整性校验 → 日期、Decimal、布尔、文本类型推断 → Arrow 批量写入私有 DuckDB → 注册授权 `dataset` 视图 → Agent 查看实际 schema → 指标参数查询或探索性只读 SQL → 保存真实行集与查询引用 → 生成答案及可检查的图表。

**非结构化知识**：上传原件 → 保存原始文件和哈希 → 持久化 IngestionJob → 独立 worker 领取 → Docling 解析结构及表格（TXT 明确使用文本解析）→ HybridChunker 生成 LlamaIndex TextNode → 调用真实嵌入接口 → 写入显式向量 Chroma → SQLite 保存全文、页码、章节、模型指纹 → 同一事务激活新版本并更新 FTS5 → LlamaIndex Retriever 合并向量与中文关键词召回 → 可选 HTTP 重排 → 原文证据引用。

业务文件进入 DuckDB 后即可查询，不需要转成自然语言向量。相同 Excel 也可以上传知识库用于文本语义检索，两条链路承担不同用途。

## Agent 执行

使用 `llama_index.core.agent.workflow.FunctionAgent` 实际执行循环，不是服务端关键词路由。可用工具如下：

| 工具 | 输入与作用 |
| --- | --- |
| `list_available_resources` | 本次选择的知识库、数据源与指标定义 |
| `search_knowledge` | 改写查询后可再次检索，返回全文证据及来源 ID |
| `read_document_section` | 读取命中切片与前后相邻切片 |
| `get_business_schema` | 查询实际授权字段、类型与 SQL 方言 |
| `query_metrics` | 使用已保存口径，绑定开始包含、结束不包含的日期参数 |
| `execute_readonly_sql` | 执行受控探索查询，返回真实结果、SQL、截断标记 |

模型通过工具调用决定下一步。默认最多 12 次 Agent 迭代、16 次工具调用、180 秒执行时间，并有估算 token 预算；同一参数重复调用超过两次会返回错误。实际多轮策略依赖模型工具调用能力，需要用真实业务验收集评估。

业务查询生成 Q1、Q2 等引用，文档证据生成 S1、S2 等引用。回答若引用未执行的查询或未检索的来源，会被拒绝；该校验只保证引用存在，不能替代答案与证据是否一致的语义评估。检索内容被提示为不可信数据。中间推理文本不发送给前端，界面显示工具开始、结束、证据和最终回答。

## 代码边界

| 目录 | 责任与扩展点 |
| --- | --- |
| `backend/app/api` | HTTP 校验、鉴权、响应，不负责 Agent 规划 |
| `backend/app/application` | AgentRun 输入快照、后台执行、事件持久化与续接、文件导入用例 |
| `backend/app/agents` | LlamaIndex 工作流、工具暴露、预算与引用校验 |
| `backend/app/connectors` | 按 source kind 派发 schema 和只读查询；本地查询与可选外部适配器隔离 |
| `backend/app/analytics` | SQL AST 策略、JSON 数值契约、结果驱动的图表与卡片 |
| `backend/app/ingestion` | 文档解析与幂等版本化索引 |
| `backend/app/retrieval` | LlamaIndex Retriever、RRF、重排、原文读取 |
| `backend/app/infrastructure` | 显式嵌入、向量索引、FTS5、文件/S3、密钥、观测 |
| `backend/app/workers` | 默认数据库 Agent/文档任务 Worker；可选 Celery + Redis 调度适配器 |
| `backend/migrations` | 版本化数据库升级，兼容旧 SQLite 表 |

新增数据源优先实现 `inspect_source(source)` 与 `execute(source, sql, params)`，在 registry 中注册，并补齐对应 SQL 方言策略。模型服务通过独立 LLM/Embedding 配置接入，不依赖 Chroma 隐式下载的嵌入模型。

## 一致性与隔离

- 身份由认证上下文确定；资源所有权在聊天入口、工具执行和检索 SQL 中再次检查，浏览器传入的 ID 不能扩大权限。
- 本地业务文件限制在当前用户的 `data_sources` 目录内。DuckDB 使用只读连接，禁用 external access、自动安装/加载扩展，设置内存、线程和查询超时；SQL AST 只允许单条 SELECT、授权关系及函数白名单，外层限制返回行数。
- 表头、空文件、行列错位、重复列名、公式和错误单元格会明确拒绝。前导零编码保留文本；空值保留 NULL。每次导入生成独立快照，不覆盖旧文件。
- 嵌入模型由端点与模型 ID 组成指纹；检索按有效索引的指纹查找仍配置的对应模型并校验维度，多个模型分组分别召回后融合。全库重建固定加密模型配置快照，所有任务 staged 后在同一 SQL 事务中激活；任一任务耗尽重试则整批失败、保留旧有效版本。重建期间禁止上传、单文档重建和删除。迁移完成前应保留旧模型配置。SQL 和 Chroma 都按用户、知识库及有效版本过滤。
- 新向量先写入，SQLite 中的切片与 `active_version` 在事务提交后才可见。解析或嵌入失败不切换有效版本，旧版本仍可检索。FTS5 通过同事务触发器同步更新。
- Agent Worker 用原子条件 UPDATE 领取 `queued` 运行，通过租约恢复 Worker 中断的运行；不同会话使用有界并发，同一会话最多一个活动运行。浏览器断连只停止 SSE 订阅，不取消 Agent。文档任务仍由现有队列领取和重试策略处理。
- 删除与版本切换在同一 SQL 事务中写入独立 MaintenanceJob，worker 幂等清理指定原件、解析产物和向量，自动重试五次后可手工重新提交。维护任务不依赖被删除文档的外键；旧版本清理不能删除有效版本，也不会删除仍被其他文档引用的旧原件。历史运行和聊天中的证据快照保留，仍需按业务保留策略另行治理。
- 索引修复从 SQL 有效切片中补回缺失 Chroma 向量，并按用户/知识库清理孤立条目，保留 queued/processing/retrying/staged 任务版本，避免误删尚未激活的向量；同时重建 FTS5。修复不重新嵌入，无法替代丢失 SQL 切片后的重建。修复任务当前面向单机默认 Chroma/FTS5 路径。
- 默认混合检索以余弦相似度阈值筛选向量候选；嵌入、模型配置或向量索引失败时明确返回关键词降级警告，重排失败时返回融合排序警告。纯向量调试模式遇到向量错误直接失败。排序得分不是概率，关键词命中不受向量阈值控制。
- 运行事件按序写入 `RunEvent`，最终状态为 completed / partial / failed / cancelled。客户端断连不改变运行状态；Worker lease 过期后，运行会被标为失败（用户已请求停止的运行标为 cancelled）。真实模型错误不会转换为模拟成功答复。
- SQLite 启用 WAL、busy timeout、外键；应用表结构只由 Alembic 管理。运行代码不使用 `create_all` 覆盖或猜测 schema。

## 部署范围与后续扩展

当前选择满足单机业务试点：一个 API、一个文档 worker、本地 SQLite / Chroma / DuckDB。它不提供多机调度、高可用、企业组织级 RBAC 或文件自动同步。用户级数据隔离不能替代组织的部门权限体系。

需要扩展时，先保持应用接口与证据契约稳定，再替换应用数据库、向量服务、对象存储及任务队列。仓库保留独立的 PostgreSQL 与 Celery 可选适配器，依赖在 `requirements-postgres.txt`、`requirements-celery.txt`，当前默认安装与 Compose 均不启用；这些可选服务需要单独集成验收。

模型、嵌入、PDF/OCR 模型下载及可选重排均属于外部边界。上线前以实际文件验证字段、币种、日期、去重口径、引用准确率及任务完成率。对因果解释和证据充分性仍需业务评估，引用存在校验不能证明结论正确。

## 框架依据

工具调用循环使用 [LlamaIndex Agent 文档](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/) 定义的 FunctionAgent。DuckDB 的文件访问限制遵循 [DuckDB 安全配置](https://www.duckdb.org/docs/current/operations_manual/securing_duckdb/overview)，并叠加应用层 SQL 白名单和用户目录检查。

## 回答交付协议

最终回答、延伸问题与独立图表的职责划分见 [统一回答协议与实施方案](unified_answer_protocol.md)。最终答案经过结构校验后统一持久化和展示；工具原始结果保留在执行事件中。
