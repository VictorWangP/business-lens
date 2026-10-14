# LangGraph 版本实现说明

日期：2026-10-14。分支、目录：`rag-langgraph`。采用 LangChain/LangGraph + Docling + 官方 AG-UI/assistant-ui 组合。

## 1. 编排与上下文

`backend/app/agents/executor.py` 使用 `create_agent`，没有应用自建的 Agent 推理循环。原生 middleware 承担模型/工具调用限制、历史摘要；ToolStrategy 承担结构化答案生成及 schema 错误纠正。业务校验通过框架 after_model 扩展点有限纠正一次。

摘要按 provider 可见消息的 token 触发，保留最近 token 范围；工具 artifact 中的完整表格不进入模型输入。模型窗口和累计 token 预算有独立输入守卫。模型窗口默认 32768，应与配置的真实模型一致。

checkpoint 按用户、会话、业务范围版本隔离。工作空间更新后建立新的模型上下文，旧聊天仍可查看。用户偏好与业务事实分开，聊天摘要不充当关系数据库或文档事实的权威来源。

精确查询保存在已授权执行的证据事件中，使用全局稳定 ID。后续问题可通过 `read_query_result` 获取，最终答案引用历史结果时也进行授权解析。文档引用采用稳定 chunk 引用，复用历史引用前检查当前访问权及有效版本。

## 2. 后台运行与标准事件

FastAPI 负责认证、固定范围、提交与订阅；worker 负责有界调度；LangGraph 负责步骤状态。关闭浏览器或切换会话只断开订阅，显式停止才发送服务端取消请求。

`DurableLangGraphAgent` 只扩展官方适配器的 `prepare_stream`：进程故障后以 `input=None` 继续未完成节点。已完成 checkpoint 恢复时直接投影已有结果。不会为故障恢复再次添加同一用户问题。

用户条件缺失时，工具调用 LangGraph `interrupt`；官方适配器输出标准 interrupt outcome，前端使用官方 hooks 显示澄清输入并提交 resume。暂停任务占用会话活动执行槽位，防止另一个问题覆盖暂停上下文。

事件持久化后通过官方 `EventEncoder` 重放。前端使用 `HttpAgent` + `useAgUiRuntime`，删除两套 SSE 帧解析、`applyRunEvent` 和 App 中的第二份消息状态。

最终正文、业务数据 part 与完成状态在同一事务发布。进程重启不会重复追加半段正文。人工恢复建立新的事件重放起点，并创建新的 assistant 消息承载继续执行的答案，以匹配官方 runtime 的消息分段；旧暂停消息保留归档。重放仅包含当前执行段，不发送缺少起始事件的工具结束事件；完整操作时间线由最终业务 data part 保存。

## 3. 展示边界

| 内容 | 公开展示方式 |
| --- | --- |
| 业务结论 | 校验后的编号 Markdown 标题与正文 |
| 表格/图表/指标 | `ACTIVITY_SNAPSHOT: business-answer` → 官方 runtime 的命名 data part → 业务组件 |
| 延伸问题 | 同一结构化答案中的恰好三个问题；关闭时为零；原生 Suggestion 发送 |
| 工具过程 | 标准 tool start/end 的安全操作名称，完整顺序，默认折叠 |
| 引用 | 已授权来源卡片、页码和原文定位 |
| 内部草稿、摘要、图状态、工具参数与结果 | 不进入公开答案通道 |

未知 data part 使用空 renderer，不能回退打印 JSON。公开流不透传图 snapshots、RAW、模型中间 text 或 schema 工具调用。工具上下文只给必要证据，不向模型重复发送应用图表配置、SQL、完整数据数组。

这是应用的业务展示契约；不自建通用 UI DSL。assistant-ui 负责通用消息、Composer、复制、语音、工具/数据 part 和暂停状态。当前产品输入仍以文本问题为主，新增媒体生成/上传业务时应沿用原生媒体 part，不额外建立消息协议。

## 4. 文档、检索与存储

Docling 官方 `DoclingLoader` 接受一次转换后的结果，结合 HybridChunker 输出 LangChain Document，保留页码、章节、provenance 和 element refs。TXT 使用成熟 RecursiveCharacterTextSplitter。检索器继承 LangChain BaseRetriever。

保留授权过滤、索引 staged/active 发布、embedding 模型指纹、失败重建保持旧版本、SQL 只读与金额精度等业务规则。OpenAI SDK 的 embedding 适配保留索引排序及向量完整性校验；直接套一个 wrapper 会丢失这些检查，因此不增加额外包装层。

新版应用 schema 为一个全新 Alembic 初始版本 `0001_langgraph`，删除旧 schema 兼容迁移和旧凭据迁移启动逻辑。不读取旧数据库重建新版。

## 5. 保留的自定义代码

- 资源授权、SQL policy、精确数据与证据引用。
- 调度记录、lease、取消、持久事件重放和应用归档。
- 原始事件的公开出口许可清单与安全投影。
- 图表、表格、指标、来源卡片等业务 UI。
- 模型配置、反馈、常问统计和用户偏好等产品业务。

框架承担 Agent 循环、摘要策略、checkpoint、interrupt/resume、标准事件转换、消息聚合和通用 UI。不能为了减少数行适配代码而撤掉授权、数据精度、向量完整性或结果引用校验。

## 6. 官方参考

- [LangChain 原生 middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- [assistant-ui AG-UI runtime](https://www.assistant-ui.com/docs/runtimes/ag-ui/overview)
- [AG-UI LangGraph 官方集成源码](https://github.com/ag-ui-protocol/ag-ui/tree/main/integrations/langgraph)
- [Docling LangChain 集成](https://github.com/docling-project/docling-langchain)

具体适配结论以本项目锁定版本的源码与实际测试为准；不将不同版本 API 示例混用。
