# 纯关系数据库问数：LlamaIndex 与 LangGraph/LangChain 选型

日期：2026-10-14　状态：**待审核的条件选型，未实施**

## 1. 前提与结论

本评估按用户新设定：不考虑知识库文档解析和检索，仅保留关系数据库问数；需要编排、历史持久化、上下文压缩/摘要、工具调用、前端会话流及暂停恢复；不计既有实现迁移复杂性。

**推荐 LangGraph 作为执行、状态和 checkpoint 底座，LangChain 提供模型/工具接口、create_agent 与成熟 middleware，assistant-ui 提供 UI。**

这是一项基于目标能力组合的工程判断，不是 SQL 准确率或性能实测。推荐不意味着 LlamaIndex 缺少编排或恢复能力：当前 Workflows 已支持上下文快照、人工交互，以及 DBOS durable runtime。但在本范围内，LangGraph/LangChain 对 thread、checkpoint、摘要、interrupt 与专用 UI adapter 的组合更直接。

本结论取代 [综合重构方案](ai_chat_refactor_proposal.md) 中“继续使用 LlamaIndex”的**纯数据库场景选型**。若仍保留原有文档/RAG 产品范围，需要另行整体评估。本轮不会删除知识库代码、替换框架或安装依赖。

## 2. 两个候选方案应当完整比较

- **LlamaIndex 方案**：FunctionAgent/AgentWorkflow + 现代 Memory/blocks + Workflow Context + 持久化快照或 DBOS + AG-UI/前端 adapter。
- **LangGraph/LangChain 方案**：LangGraph 状态图/checkpointer + LangChain create_agent/工具/摘要 middleware + 标准服务 API 或 AG-UI + assistant-ui adapter。

不能拿当前只使用一部分 LlamaIndex 能力的实现，与完整 LangGraph 体系比较；也不能把安装 LangGraph Python 库等同于已经获得会话服务、任务队列和浏览器恢复。

LangChain 和 LangGraph 在这里是互补关系：高层 Agent/middleware 运行在 LangGraph 体系上。纯 LangChain 的工具链调用不替代持久化执行；手写完整 LangGraph Agent 循环也会浪费高层框架已有能力。[LangChain Agent](https://docs.langchain.com/oss/python/langchain/agents)、[LangGraph 概览](https://docs.langchain.com/oss/python/langgraph/overview)

## 3. 能力比较

| 能力 | LlamaIndex 完整方案 | LangGraph/LangChain 完整方案 | 本场景判断 |
| --- | --- | --- | --- |
| 基础数据库问数 | SQL/数据库工具与 FunctionAgent 能实现 | SQL 工具与 create_agent 能实现 | 两者均可，不能据此判断准确率 |
| 明确步骤/循环/分支 | 事件驱动 Workflow、typed events、steps | StateGraph、节点、条件边、子图 | LangGraph 更贴合显式状态控制 |
| 工具调用 | FunctionTool、调用循环与结果事件 | tools、ToolNode/create_agent、middleware | 基础相当；后者通用控制策略更集中 |
| 会话状态持久化 | Memory/chat store 与 Context 分工；需明确协调 | thread + checkpointer 保存图状态，Store 保存跨会话数据 | LangGraph 的执行/会话模型更统一 |
| 上下文 token 窗口 | 现代 Memory 原生支持 | 短期记忆、裁剪与 middleware | 两者均可 |
| 历史摘要 | blocks 可扩展；旧 ChatSummaryMemoryBuffer 已弃用 | 内置 SummarizationMiddleware | LangChain 更适合直接复用 |
| 工具上下文清理 | 应用/Memory block 策略 | ContextEditingMiddleware 等现成策略 | LangChain 更方便，仍需业务证据策略 |
| 人工暂停/续跑 | InputRequired/HumanResponse + Context 快照 | interrupt + Command(resume) + checkpoint | LangGraph 组合更直接 |
| 故障恢复 | 手动 step 快照；DBOS 可自动持久化 | 原生 checkpointer、恢复/重放及 durability 选项 | LangGraph 原生；LlamaIndex+DBOS 也可实现 |
| 执行调试/状态检查 | Workflow 事件、可视化与 tracing | checkpoint/state history、更新状态、time travel | LangGraph 更适合状态驱动排查 |
| UI 集成 | 可通过 AG-UI 接 assistant-ui | assistant-ui 专用 LangGraph/LangChain runtime，也可 AG-UI | LangGraph 端到端选择更多 |
| 图片/图表/表格 | 都需要结构化展示与业务 renderer | 同左 | Agent 框架不替代 UI 与精确数据控制 |
| 文档/RAG 专用能力 | 是体系的重要优势 | 也有生态能力 | 本次不计入决策 |

结论依据是能力组织和现成接口，而不是迁移工作量。LangGraph 的状态 schema、reducer、checkpoint 运维同样需要设计，不会让业务程序变成零代码。

## 4. 上下文压缩与摘要

### 4.1 为什么这里更推荐 LangChain

内置 `SummarizationMiddleware` 可配置 token/消息触发条件和近期保留范围，适合长对话的自动压缩；还有上下文编辑、模型/工具调用限制、重试等策略，不需要分别实现多个拦截器。[官方 middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization)

LlamaIndex 现代 Memory 支持 token 窗口和 memory blocks，但不默认启用滚动摘要；FactExtractionMemoryBlock 的事实抽取不等于有时序的任务摘要，旧摘要 buffer 已标记弃用。要采用现代推荐接口并保持同等摘要行为，通常需要一个会话摘要 block/适配。[官方 Memory](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/)

### 4.2 两者都必须遵守的问数规则

- 摘要保留用户目标、指标定义、维度、筛选/时间口径、单位、纠正和未完成事项；业务参数尽量作为独立结构化 state 保存，不能只依赖自然语言摘要。
- 查询结果保存在结果仓库；模型只拿有预算的相关行、聚合值、截断说明和引用，不复制图表数组或所有展示表格。
- 摘要记录结果/运行 ID 和查询时间，旧结果不能充当“最新数据”。只读查询重跑也可能读到新数据，恢复要求明确结果版本。
- middleware 的 token 触发不代替完整请求预算；仍须配置实际模型窗口、系统/工具 schema、输出预留和计数误差余量。
- 摘要与跨会话偏好分开；压缩模型上下文不删除用户可查看的完整聊天归档。
- 通用摘要不能保证指标数值和口径永远正确；需要业务验收。摘要、SQL 草稿和结果引用都不提升为权限规则。

## 5. 历史持久化：区分三类数据

| 数据 | 建议权威存储 | 用途 |
| --- | --- | --- |
| 执行/模型会话状态 | LangGraph 持久化 checkpointer | 最近消息、压缩状态、结构化业务参数、待执行节点、interrupt |
| 用户可查看的完整聊天 | 应用 append-only 归档/版本化 UI parts | 摘要后的原始历史、图表/表格顺序、复制/导出 |
| 查询结果与资产 | 受权结果/资产仓库 | 精确行集、查询时间/范围、图片等 |

checkpointer 的工作状态可能被压缩、更新或清理，因此不能把其“最新 state”直接当作永久完整聊天记录。Store 用于跨 thread 数据，不自动知道哪些业务事实可以长期信任。

生产采用数据库 checkpointer，单机开发可选 SQLite，生产通常采用 PostgreSQL。InMemorySaver 不提供跨进程持久化；checkpoint 保留周期和体积需要管理。[持久化](https://docs.langchain.com/oss/python/langgraph/persistence)、[checkpointer](https://docs.langchain.com/oss/python/langgraph/checkpointers)

`thread_id` 不是鉴权凭证。应用仍需验证用户、业务空间及来源权限；按 scope version 隔离/重建压缩状态，防止撤销来源后继续从旧摘要获得数据。

## 6. 暂停/恢复：四种不同能力

| 情况 | 所需能力 | 选型含义 |
| --- | --- | --- |
| 刷新/断网后继续看 | 后台运行 + stream/event replay | 两者均需服务层支持，checkpointer 不等同于 SSE 重放 |
| 等用户补充或确认 | 有标识的 interrupt + 持久化待办 + 授权 resume | LangGraph 原生组合较完整 |
| Worker 崩溃后继续 | 已持久化执行边界 + 重新调度 + 幂等 | 两者能做；LangGraph 原生 checkpoint，LlamaIndex 可 DBOS |
| 用户点停止后想继续 | 取消语义、保存策略和恢复/新尝试规则 | 不能把 cancel 自动当作 pause；产品需明确定义 |

LangGraph `interrupt` 配合相同 thread 的 `Command(resume=...)` 恢复。恢复时中断节点从头执行，中断之前的代码可能再次运行；因此副作用必须幂等或移到受控步骤。[官方 interrupt](https://docs.langchain.com/oss/python/langgraph/interrupts)

有持久化 checkpointer 时，可以选择同步落盘等 durability 策略；但未完成节点仍可能重执行，持久化模式也影响丢失窗口。不要承诺任意一行继续或对外部系统恰好执行一次。[durability](https://docs.langchain.com/oss/python/langgraph/checkpointers#durability-modes)

**LlamaIndex 也支持此类能力。** 普通 Workflows 可通过 Context.to_dict/from_dict 和 step 边界 checkpoint loop 恢复；官方 DBOS runtime 进一步自动保存 step transition。DBOS 文档同样提醒重放可能重复执行，仍需幂等。[手动 durable workflow](https://developers.llamaindex.ai/python/llamaagents/workflows/durable_workflows/)、[DBOS runtime](https://developers.llamaindex.ai/python/llamaagents/workflows/dbos/)、[人工交互](https://developers.llamaindex.ai/python/llamaagents/workflows/human_in_the_loop/)

因此选择 LangGraph 的理由是所需能力在同一状态/checkpoint/前端生态中更集中，而非 LlamaIndex “没有恢复”。这些是当前生态能力，不代表工作区当前版本已安装/启用 DBOS 或 LangGraph。

## 7. 前端标准事件与部署选择

### 推荐主路径：官方 LangGraph 服务 API + assistant-ui 专用 runtime

assistant-ui 已提供 `@assistant-ui/react-langchain`（封装上游 useStream）和 `@assistant-ui/react-langgraph`（SDK runtime），覆盖图状态、消息、工具和 interrupt 等能力。[LangChain runtime](https://www.assistant-ui.com/docs/runtimes/langchain)、[LangGraph runtime](https://www.assistant-ui.com/docs/runtimes/langgraph/overview)

采用兼容的 Agent Server API 时，优先复用其中一个官方 runtime，不同时叠加 AG-UI runtime。现代薄 adapter 可减少前端自行管理状态；选择前核对安装版本对历史、取消和所需 UI parts 的支持。

注意：

- Python 中 `StateGraph.compile()` 不会自动生成 HTTP thread/run 服务；专用前端 adapter 需要兼容的服务 API，不直接消费任意 FastAPI SSE。
- Agent Server 提供 thread/run 等服务职责；部署前核对自托管形态、鉴权、许可、数据驻留和基础设施。采用 OSS 库不等同于所有服务产品都免费/同一许可。
- Agent Server 管理调度时，不再重复实现另一套 AgentRun 调度和线程状态；应用保留索引/审计/授权映射即可。若保留自建 worker，则它负责调度，checkpointer 负责步骤状态，两个层次不能混为一谈。
- 框架原生 streaming 是生态协议；AG-UI 是跨框架协议。所谓“标准事件”应明确选择哪一种。[Agent Server](https://docs.langchain.com/langsmith/agent-server)

### 自建 FastAPI/跨框架路径：LangGraph + AG-UI + assistant-ui

不采用兼容服务 API 或需要跨框架协议时，可通过 AG-UI adapter 暴露 LangGraph，再接 `useAgUiRuntime`。继续由应用承担后台调度、授权、运行取消和断线重放。选择这一条即可，不为每种内容维护私有事件。

两条路线都需要隐藏 SQL 生成、摘要和结构化输出等内部模型流，只公开经校验的回答和操作状态。LangGraph 支持按节点/tag 筛选消息流；仅有过滤 tag 还不构成全路径业务校验。[streaming](https://docs.langchain.com/oss/python/langgraph/streaming)、[assistant-ui AG-UI](https://www.assistant-ui.com/docs/runtimes/ag-ui/overview)

## 8. 纯 SQL Agent 推荐的编排

不需要多 Agent。先采用 LangChain create_agent + middleware；需要强制执行的校验/暂停边界用 LangGraph 节点表达。不能以减少自定义为理由省略确定性的 SQL 检查。

建议步骤：

1. 读取当前用户、授权来源、已确认业务参数和会话状态。
2. 判断是否需要澄清；需要则 interrupt，保存待补充字段。
3. 获取授权 schema/指标，生成受限 SQL 或选择预定义指标。
4. 通过确定性 SQL policy、参数和资源预算检查；不合格进入有限纠正循环。
5. 对确实需要确认的高成本/特殊范围查询暂停；普通只读问数不必每次人工批准。
6. 执行查询并持久化结果 ID/时间/范围；按预算向模型返回证据视图。
7. 生成结构化 AnswerPlan，校验结论引用和图表能力。
8. 提交最终 UI parts/聊天归档及执行状态，按策略压缩后续模型上下文。

若使用 create_agent 的内部工具循环，SQL 执行工具本身必须调用 policy；若使用显式图校验节点，不能让其他路径绕过它。middleware 直接挂在 create_agent 上；普通自定义 StateGraph 节点不会自动运行这些 middleware，需要明确的集成点。

## 9. 仍应保留的应用代码

- 用户/租户/空间鉴权、thread/run 所有权和恢复时权限复核。
- 只读数据库账户、授权视图、SQL policy、超时、行数/成本限制、结果精度和审计。
- 指标语义、时间与币种口径、来源和结果引用验证。
- 最终结构化输出、绘图源码隔离、真实表格/图表和三个建议的业务校验。
- query/asset 受权读取，完整聊天展示归档，删除与保留策略。

LangChain 官方 SQL 示例明确提示示例工具不是生产安全边界，不能直接替换当前 SQL 防护。[官方 SQL Agent](https://docs.langchain.com/oss/python/langchain/sql-agent)

两个框架都不会自动提高 SQL 正确率、保留所有摘要细节，或实现整个业务系统的 exactly-once。这里只能判断架构适配性，效果仍需真实模型与故障/恢复验收。

## 10. 最终建议

在本次前提下，建议审核通过：

**LangGraph 状态/持久化 + LangChain Agent/middleware + 数据库 checkpointer + assistant-ui 官方 runtime + 关系数据库只读工具。**

- 优先现成 SummarizationMiddleware，删除计划中的自定义 SessionSummaryBlock 通用摘要实现；业务参数与结果引用仍显式保存。
- 优先兼容服务 API 与专用前端 adapter，减少自建会话流桥；需要自建 FastAPI 时采用 AG-UI 路线。
- LlamaIndex 退出纯 SQL Agent 核心链路；不同时保留两套 Agent Memory、执行状态和工具循环。
- 若未来主要需求重新回到复杂文档/RAG，或团队明确偏好事件驱动 Workflows + DBOS，再重新比较 LlamaIndex 完整方案。

该结论是条件性方案建议，尚未授权删除现有知识库能力或开始框架迁移。依赖版本、部署形态和验收实施须在方案审核后确定。
