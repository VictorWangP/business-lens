# AI 问答通信、内容展示与上下文管理重构方案

日期：2026-10-14　状态：**待审核，尚未实施**

最新完整范围评比：将文档解析、索引、检索重新纳入后，目标方案对比与推荐见 [完整项目框架评估](full_project_framework_evaluation.md)。当前主选 LangGraph/LangChain + Docling；LlamaIndex 可按明确的复杂 RAG 收益作为检索组件使用。本文件保留最初的诊断与设计细节，涉及框架归属的结论以新评估为准。

补充范围：在“移除文档/RAG、仅保留关系数据库问数，并要求持久化暂停恢复”的新前提下，框架选型调整为 LangGraph/LangChain，详见 [纯 SQL Agent 框架评估](sql_agent_framework_evaluation.md)。本文件关于展示边界、权限和精确结果的分析仍适用；其 LlamaIndex/自定义摘要 block 选型不作为该新范围的推荐。

## 1. 决策摘要

**建议重构通信与消息数据模型、数据展示边界和上下文管理；继续复用现有 UI 组件、数据分析工具及后台任务。**

本判断首先考虑目标架构的长期清晰度与成熟能力复用，不以当前代码迁移工作量作为否决理由。不是所有自定义逻辑都应删除：业务授权、结果准确性、证据、任务取消与可恢复执行仍需应用负责。

| 范围 | 判断 | 建议 |
| --- | --- | --- |
| UI 与 Agent 通信 | 自定义和重复处理明显过多 | AG-UI 标准事件 + assistant-ui 官方 runtime |
| 消息/状态模型 | 展示文本、业务容器和 runtime parts 反复转换 | 服务端统一生成展示投影，前端 runtime 单独持有 UI 消息 |
| 普通文字/Markdown | 已使用成熟组件，无需重写 | 保留 MarkdownTextPrimitive/GFM，收缩新消息过滤 |
| 图片 | 缺少完整附件/资产/模型输入链路 | 使用原生 image/file parts 和 attachment adapter |
| 图表 | Recharts 合适；自定义传输、单图槽位和猜测字段需调整 | 保留图表库，按结果 ID 传递多个独立展示对象 |
| 查询表格 | 真实数据被转成 Markdown 后再次解析，边界不合理 | 查询表格使用 data part + 现有 shadcn Table |
| 上下文压缩 | 能力不足，且有两层不同口径的裁剪 | 显式 LlamaIndex Memory + token 预算 + 持久化滚动摘要 |
| 长期用户偏好 | 可保留，不能替代会话摘要 | 与会话记忆和业务证据分开管理 |
| Worker/RunEvent/权限 | 有必要，协议库不能替代 | 保留并规范与 runtime 的适配 |

推荐组合：**assistant-ui + AG-UI + LlamaIndex FunctionAgent/Memory + Pydantic + 现有 Recharts/shadcn**。正常聊天不新增通用布局 DSL、不执行模型生成的绘图代码，不引入另一套 UI 框架。

本提案是 [2026-10-13 集成评估](assistant_ui_llamaindex_review.md) 的范围扩展，涵盖多媒体、结构化输出和上下文生命周期。此前文档是现状研究记录，本文件为待审核的目标方案。已经实现的 [统一回答协议](unified_answer_protocol.md) 在新方案中保留为业务约束，展示文本生成方式会调整；审核前不改变现有行为。

## 2. 审查方法与证据范围

- 检查当前应用源码、实际安装的 assistant-ui API、LlamaIndex 0.14.25 源码及官方文档。
- 检查通信入口、运行持久化、前端状态、Markdown、图表、图片/附件入口、记忆和模型配置。
- 本轮没有修改业务代码、安装依赖、执行测试或真实模型问答。
- 本地数据库未找到已完成且含新 `answer` 事件的可用样本，因此不提供运行流量、压缩收益或真实模型成功率的实测结论。
- 以下“过于复杂”“推荐”等为基于代码与能力边界的工程判断，不是行业统一排名。框架支持某项功能，不等于本项目已经验证该功能。

主要入口（行号对应本轮审查时的源码）：

| 位置 | 证据 |
| --- | --- |
| `frontend/src/App.tsx:169/248/453/618` | 事件 reducer、恢复订阅、发送解析、ExternalStoreRuntime |
| `frontend/src/lib/chat-runtime.ts:6` | 应用消息到 runtime 消息；合成图表工具调用 |
| `frontend/src/lib/answer-presentation.ts:5` | 前端按 AST 移除代码/HTML |
| `frontend/src/components/chat/MarkdownContent.tsx` | 已使用官方 Markdown 和 shadcn Table |
| `frontend/src/components/chat/ChartViewer.tsx` | 已使用 Recharts；单 Y 轴、多序列 |
| `frontend/src/components/chat/Composer.tsx` | 文本输入，禁用粘贴附件，没有配置 attachment adapter |
| `backend/app/application/chat.py:62/75/80/213` | 最近 12 条、24,000 字符、偏好记忆、消息投影 |
| `backend/app/agents/executor.py:145/171/187/198` | 查询结果、累计 token 预算、默认 Memory、忽略 AgentStream |
| `backend/app/agents/answer.py:68/109` | 自定义 JSON 验证和查询表格 Markdown 序列化 |
| `backend/app/services/memory_service.py` | 规则抽取画像/话题；不是滚动摘要 |
| `backend/app/analytics/presentation.py` | 图表字段推断、最多两个数值系列、转换为 float |

## 3. 当前实现的具体问题

### 3.1 通信：协议与消息组装重复

当前经过 FunctionAgent 原生事件 → 应用事件 → RunEvent/Message 快照 → SSE → App 消息 → assistant-ui parts。

1. 首次 POST 和恢复 GET 各自实现 reader、TextDecoder、帧切分和 JSON 解析。当前 parser 适配服务端 LF/单 data 行格式，没有发现一般化的多行/CRLF SSE 处理和自动退避重连。
2. `persist_run_event` 与 `applyRunEvent` 分别解释同一组业务事件；新增字段需同步修改多个分支。
3. `isLoading`、多个 ref、消息 status 和 runtime status 共同表达一次运行。`partial` 当前显示为 runtime complete，同时隐藏建议，状态语义不一致。
4. 真正的工具事件走 `tool_start/tool_end`；另一个 `tool_call` 表示图表/指标，前端又伪装成 `render_chart/render_metrics`。执行工具和展示产物的名字与职责混杂。
5. 即时操作列表与持久化消息只保留工具事件 type/name，丢失调用 ID 和配对信息；完整信息要另查运行记录。

**判断：值得替换这一层。** 这些不是问数业务独有能力，标准 runtime 已经覆盖大部分解析和消息生命周期。

### 3.2 展示：已有成熟渲染器，但承载模型不统一

当前 `Message.content` 仅为字符串，`tool_calls` 同时容纳状态、图表、指标、原始查询、最终答案和建议，引用另外保存。`metadata.custom.appMessage` 又携带整份业务消息。

- 文字由官方 Markdown 渲染，合理；编号标题是产品要求，必要的薄定制。
- 查询表格由 `render_answer` 拼为 Markdown，浏览器再解析成表格；原始行集同时存在于 query_result、tool result 和消息快照。完整证据、展示数据与模型输入应有不同长度，但共享明确的结果来源。
- `calls.chart/calls.metrics` 每次被覆盖；前端一条消息最多保留一个图表槽位，不能自然表达多次查询的多张图。
- 图表数据由首个分类列和前两个数值列推断，金额变成 float。用于视图可以近似转换，不能再把这些展示值作为财务精确计算依据；序列标签、单位、轴能力需要显式约束。
- `ChartConfig` 声明 area，但当前 renderer 没有对应分支；双 Y 轴也未实现。模型无法仅凭“可画图”判断实际能力。
- 正文、图表、表格和引用没有统一的稳定 part ID 与顺序记录。未来交错展示及历史恢复需要避免拼接顺序与即时显示不一致。

**判断：保留渲染库，重构内容承载和结果引用。** 自己维护一个业务 ChartView/TableView 是合理封装；为每种内容再设计一个独立传输事件、状态槽位和恢复流程则会继续放大复杂度。

### 3.3 图片：当前是能力缺口

没有完整的图片资产对象、上传/授权读取/持久化、image part、附件 adapter 和多模态模型输入映射。Markdown 可能显示 URL 图片，但这不等于具备可靠的图片消息能力。

目标应复用原生 image/file parts 和附件生命周期。区分“展示服务端已产生的图片”与“用户上传图片让模型理解”：后者还要求模型支持视觉、正确的 MIME 和图像 token 估算；不能仅加一个 `<img>` 就宣称支持。

### 3.4 上下文：实际是截断，不是跨轮压缩

当前链路：按用户/会话/空间版本读取最近 12 条消息 → 移除历史代码块 → 从新到旧累计 24,000 字符 → 传入 agent.run(chat_history=...)。

FunctionAgent 在未显式传 memory 时，当前安装版本内部创建 `ChatMemoryBuffer`，按 LLM metadata 再做 token 限制。因此已有框架 token 裁剪，并非完全没有 Memory；但应用早先丢掉的历史不可能由该 buffer 恢复。

具体缺口：

1. 字符数与 token 数不一致，且缺少系统提示、工具 schema、当前用户输入、证据和输出预留的统一预算。
2. 最近 12 条限制可能先丢掉用户早期确认的口径、筛选条件和纠正意见；没有摘要接住这些内容。
3. 从后向前遇到超限消息直接 break，未按完整问答/工具事务保留；旧错误答复也没有明确的上下文策略。
4. 显示用 Markdown 表格进入下一轮历史，重复消耗 token；工具执行时完整 SQL 行集也进入模型对话。行数限制不是 token/字节限制，长单元格仍可能很大。
5. `context_window=32768` 与 `max_tokens=4096` 固定设置，当前模型配置没有声明上下文、结构化输出或视觉能力；适配不同模型时不可靠。
6. `AGENT_MAX_TOTAL_TOKENS=64000` 是整次运行的累计成本预算，不能当作单次 32K 上下文限制。token callback 是控制成本的保护，不能替代请求前的上下文组装。
7. MemoryService 主要按关键词记录职业、偏好和话题，`ai_response` 未用于摘要，`query` 未用于相关召回。当前请求 `include_facts=False`，只注入画像；这些跨会话数据不能承担会话压缩职责。

**判断：上下文管理应优先重构。** 代码本身不长，主要问题是职责与能力不完整。需要采用框架 token Memory，而非继续增加字符阈值和正则。

## 4. 成熟方案与选型

### 4.1 通信与 UI

| 方案 | 可以直接复用 | 仍需应用负责 | 判断 |
| --- | --- | --- | --- |
| assistant-ui + AG-UI | 官方 client/runtime、事件模型、工具生命周期、状态事件 | LlamaIndex 事件桥、权限、后台恢复、业务 data renderer | **推荐**，契合 Agent 工具/运行状态 |
| assistant-ui + AI SDK UIMessage Stream | useChat/runtime、标准 text/file/source/data parts、transport | Python 事件编码、权威历史、后台恢复与取消 | 成熟可行的备选，文本及有序多媒体表达清晰 |
| assistant-ui AssistantTransport | Python assistant_stream、状态复制、命令接口 | 应用 state→UI converter、任务生命周期 | 可用，领域消息转换仍较多 |
| assistant-ui LocalRuntime + ChatModelAdapter | 原生消息/编辑等 runtime，单一 run 接口 | 原有 SSE 协议、恢复和事件转换 | 可减小 App，标准化程度有限 |
| 整体替换 Chat UI / 新增布局 DSL | 更多通用组件或布局能力 | 权限、精确数据、历史与模型输入仍要适配 | 现有 UI 已覆盖，新增抽象无充分收益 |

AG-UI 的收益来自官方 runtime 接管事件解析与消息重建，不依赖整套替换后端。LlamaIndex 官方集成的默认 AGUIChatWorkflow 另行实现工具循环；不直接用它覆盖当前 FunctionAgent，使用标准事件类型/编码器和有限的事件桥即可。[AG-UI runtime](https://www.assistant-ui.com/docs/runtimes/ag-ui/overview)、[LlamaIndex 官方包](https://pypi.org/project/llama-index-protocols-ag-ui/)

AI SDK UIMessage Stream 也支持 Python/FastAPI，**不要求引入 Node 代理或改写为 TypeScript Agent**。此前评估中 Node 代理是可避免的实现选择，不应当作它的固有缺点。它是认真保留的备选：若 AG-UI 在有序混合内容或恢复上需要维护整套自定义消息聚合器，则切换到此方案，而不继续扩张桥接层。[协议](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol)、[自定义 data parts](https://ai-sdk.dev/docs/ai-sdk-ui/streaming-data)

以上库均不能直接替代数据库任务。停止浏览器请求与停止后台执行必须分别处理；AI SDK 官方也要求可恢复流接入专门停止端点。[恢复与停止](https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-resume-streams)

### 4.2 多媒体展示

assistant-ui 已有 text/image/file/source/tool-call/data parts，以及 tool/data renderer 注册机制，工作区实际安装版本导出了 `makeAssistantDataUI`。应使用这些扩展点，保留现有 Recharts 和 shadcn Table；不自建“任意 JSON 自动生成 UI”的解释器。[Message Parts](https://www.assistant-ui.com/docs/primitives/message)、[图片 primitive](https://www.assistant-ui.com/docs/api-reference/primitives/message-part)、[Table](https://ui.shadcn.com/docs/components/table)

### 4.3 上下文与摘要

| 方案 | 特点 | 判断 |
| --- | --- | --- |
| LlamaIndex `Memory` | token 窗口、flush、memory blocks、chat store，直接传给 FunctionAgent | **推荐基础**，替代隐式默认 buffer 与字符裁剪 |
| 内置 `FactExtractionMemoryBlock` | 抽取、去重和压缩事实 | 可选会话事实块；不等同于按时间保留任务进展的滚动摘要 |
| `ChatSummaryMemoryBuffer` | 有现成摘要能力 | 已弃用，不作为新架构长期核心 |
| `Memory` + 一个薄的会话摘要 block | 复用框架 flush/token 生命周期，明确保留任务约束/纠正/待办 | **推荐补充**；摘要内容政策和保存游标是有限业务扩展 |
| LangChain `SummarizationMiddleware` | 现成 token/消息触发、尾部保留、摘要策略 | 若同时决定更换 Agent，成熟备选；无法直接插入 FunctionAgent |
| 外部长期记忆服务 | 跨会话事实/偏好召回 | 本轮无引入必要，不能替代请求 token 预算 |

官方 `Memory` 不会默认自动生成摘要；当前内置 block 不是完整滚动任务摘要。推荐方案明确保留一个有限扩展，不宣称可以零自定义完成所有业务记忆。即使不计迁移工作量，引入第二套 Agent 框架只使用一个 middleware，也会增加目标架构的概念和依赖。若后续还需要图式控制流、人工中断和 checkpoint，再整体比较 LangChain/LangGraph，避免双 Agent runtime 并行。

依据：[LlamaIndex Memory 与弃用说明](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/)、[Memory API](https://developers.llamaindex.ai/python/framework-api-reference/memory/memory/)、[LangChain 摘要 middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization)。

## 5. 目标架构：标准负责生命周期，应用负责业务规则

推荐的数据流：

1. 服务端创建带幂等键的运行，固定用户/空间版本/模型能力/历史快照。
2. ContextBuilder 读取授权历史、摘要和结果引用，使用显式 Memory 建立本次模型上下文。
3. FunctionAgent 调用现有只读查询和检索工具；完整结果交给结果仓库，模型只得到有预算的证据视图。
4. 框架生成结构化最终回答，应用做业务校验。
5. 单一 PresentationProjector 将最终答案和授权产物转换为官方消息 parts，生成同一份历史展示快照。
6. 单一 AG-UI 出口发送标准事件；服务端先留存事件再对订阅者发布。
7. assistant-ui 官方 runtime 管理当前 UI 消息；页面只通过公开 hooks/API 操作消息。
8. 摘要和 memory checkpoint 按已确认消息游标更新；客户端切换/断连不改变任务。

### 5.1 三种表示需要区分

| 表示 | 权威内容 | 不应放入 |
| --- | --- | --- |
| 业务记录/证据 | 原始查询结果、来源版本、执行事实、最终答案结构 | UI 临时加载状态 |
| UI 消息 parts | 文字、图表/表格引用、图片、引用和展示顺序 | 给模型的隐藏指令、未经校验的草稿 |
| 模型上下文 | 当前输入、近期语义消息、摘要、受限工具证据 | DOM、图表数组副本、整张展示表格、运行日志 |

三者表达不同内容，不能强行使用同一个自由文本字符串。简化点是**每种表示只有一个构造入口和写入者**，UI 快照是可再生成的投影，不是前后端各自维护一套业务事件 reducer。

实现边界限定为几个薄入口：运行协议 adapter、展示 projector、ContextBuilder 和会话摘要 block；结果与资产访问复用现有存储/授权服务。不增加插件系统、通用事件总线或通用 UI 解释器。

## 6. 通信与会话具体方案

### 6.1 单一协议出口

- 使用 AG-UI 官方模型/encoder，禁止在业务代码手写 `data:` 字符串和另一套 parser。
- 真实工具调用保留稳定 toolCallId；工具参数结束、工具执行结果和步骤结束使用各自正确语义。
- 图表等展示产物使用 data parts；真正执行的查询使用 tool parts。取消当前用合成工具调用承载所有展示数据的约定。
- 排队、partial、取消、usage、建议和证据属于有限应用 metadata/state；只为协议未覆盖的业务内容扩展，不能把现有所有私有事件原样塞进 CUSTOM。
- 初次连接与恢复连接使用同一标准解码和消息投影。恢复 adapter 只负责 run_id、cursor、鉴权、重试和重放，不能复制 SDK 的消息聚合器。
- 同时维护所有运行的任意共享大 state 没有必要；runtime 管理所选会话，服务器保存其他任务状态。

### 6.2 后台任务语义保留

- 任务继续在独立 worker 中执行；订阅接口只读运行事件。
- 创建请求使用用户范围内的幂等键，网络重试不生成重复问题/AgentRun。
- 断连、卸载、切换会话仅 detach；明确停止按钮调用按 run_id 鉴权的 cancel。
- 不把 runtime 的所有 `onCancel` 回调直接映射到服务端取消，因为切换和 teardown 也可能触发它。
- 恢复只订阅已有 run，不重新启动 Agent；区分事件重放、人工中断续跑和进程崩溃后的步骤恢复。
- 保留 `run_id + sequence` 游标。SSE 可使用 event ID 携带游标，但先核对所选 SDK 的消费方式，不能假设浏览器 fetch 会自动处理 Last-Event-ID。
- 重放从快照序号之后开始，快照和序号同事务提交；若最后工具参数帧不完整，恢复 adapter 必须能够取得完整 part 快照，防止追加重复参数。

### 6.3 历史恢复与顺序

AG-UI 历史 messages 的 content/toolCalls 分离，官方转换器明确说明部分混排顺序不能恢复。不能只存一份 AG-UI messages 然后假设混排完全等价。[官方限制](https://www.assistant-ui.com/docs/runtimes/ag-ui/runtime-options#loading-conversation-history)

目标持久化官方 runtime 的**有序 parts 展示快照**，保留 messageId、partId、runId 和完成状态。历史通过 adapter 返回这份投影，不从 Markdown、工具名或原始日志推断顺序。模型历史走 ContextBuilder，不把整个 UI parts 无筛选转成模型 messages。

如果所选 AG-UI adapter 在历史导入/后续更新时不能保留这份 parts 投影，且只能通过维护独立自定义聚合器解决，则采用 AI SDK UIMessage Stream 备选；其 ordered parts 原生承载此需求。该项是实现入口的验证门槛，不影响“必须取消私有全栈消息协议”的决策。

## 7. 文字、图片、图表、表格的统一展示

| 内容 | 标准承载 | 组件 | 模型提供什么 |
| --- | --- | --- | --- |
| 段落/编号标题 | text part | 现有 MarkdownTextPrimitive | 结论、标题和有效引用 |
| 图片 | image/file part | assistant-ui Image/Attachment | 只引用存在且授权的资产 |
| 查询数据表 | 命名 data part | 现有 shadcn Table | query/result ID 和是否展示 |
| 图表 | 命名 data part | 现有 Recharts ChartViewer | 受限类型、轴/系列字段引用 |
| 单值指标 | 命名 data part | 现有 MetricCards | 指标引用，数值由结果提供 |
| 来源 | source part + 必要业务 metadata | 原生来源能力与现有详情 | 允许引用的来源 ID |
| 工具操作 | tool part，默认折叠 | 原生 tool UI + 业务标签 | 工具调用；结果由服务端提供 |
| 延伸问题 | 消息 metadata/state + Suggestions | 原生 Suggestions | 开启时三个有效问题 |

### 7.1 文字与表格

- 普通说明性小表可继续使用 GFM。SQL 结果表直接传结构化行集/结果引用，取消后端逐单元格拼 Markdown 再解析的流程。
- 大项仍按内容组织，程序统一编号和标题样式，不固定四个栏目。
- 查询表保留列顺序、原始值、类型/单位、空值和截断说明；不要把 Decimal 先转 float 再显示精确数值。
- 复用现有 Table；有明确排序/分页需求时再使用 shadcn 官方 Data Table 方案，当前不新建通用表格框架。
- 复制/导出需要不同格式时，提供小型导出 serializer；UI 不再依赖导出 Markdown 来显示。朗读只取文字与有意义的指标摘要。

### 7.2 图表

- 查询产物以 `(run_id, query_id)` 或全局 result ID 唯一定位；Q1/S1 只在本轮展示，不作为跨轮唯一键。
- 一个结果可关联表格和图表，多结果使用多个稳定 part ID；按已校验的最终答案确定展示顺序。
- ChartView 只存受限类型、结果引用、X/系列字段、标签和单位。实际数据来自同一结果仓库，不允许模型填数组。
- 明确声明当前支持 bar/line/pie、单 Y 轴和系列上限；移除未实现的 area 声明，或在业务需要时通过 Recharts 实现后再开放。
- 双 Y 轴只有 renderer 和 schema 均实现后才允许；图表切换只改本地显示类型，不改变证据。
- 展示允许近似浮点坐标，财务汇总始终基于精确原始结果。对不可绘制结果给出业务限制，不能用 Python/配置教程替代。

### 7.3 图片与附件

- 最小持久化资产：asset ID、所有者/会话、MIME、大小、存储位置和必要来源信息；沿用现有存储基础设施，不另建资产平台。
- 服务端将授权资产解析为可显示 URL 或受控文件响应；不能依赖 blob URL 在刷新后仍存在。短期 URL 过期后按 asset ID 重新授权解析，不把浏览器地址永久当作资产 ID。
- 先支持服务端图片展示；上传/视觉理解按模型能力启用 attachment adapter。unsupported 模型明确提示，不丢弃附件后只发送文字。
- 使用现有 UI 和公开 adapter，不自建图片放大/上传状态通用组件。不要把 base64 大文件塞入每个 RunEvent、摘要或文字历史。

### 7.4 回答内容控制与原始工具结果

- 操作 UI 默认折叠，只显示动作/状态；SQL、参数和结果仍通过有权限的详情查看。
- 新格式消息在服务端完成内容校验，前端 renderer 按 part 类型展示。代码只在用户明确要求时出现在专用内容字段。
- 不采用“先显示所有模型 delta，最后再过滤”的方式；已出现的源码无法通过终态清理撤回用户看到的内容。
- 保留旧历史 AST 清理为迁移兼容入口；新消息不再每次前后端重复做同样过滤。
- 未注册/未知 data part 只显示受控占位或隐藏并记录诊断，不能回退把 JSON/工具结果打印到回答中。

## 8. 结构化回答：采用框架出口，保留业务校验

当前 FinalAnswer/Pydantic 本身规模有限且有业务价值，不应为减少行数恢复无约束自由文本。建议改为：

1. 使用 FunctionAgent `output_cls` 生成结构化结果，通过 `structured_response` 消费；内部保留小型 AnswerPlan（标题、结论、产物引用、建议），不设计任意 UI 布局树。
2. 保留单一 `validate_business_answer`：授权查询/来源/资产存在、三个建议、代码请求意图、图表能力及截断口径。
3. 校验通过再投影为 text/data/image parts。模型不能设置运行状态、执行记录或已有结果的数值。
4. 缺少 structured_response 视为失败；只允许一次受限最终格式修复，不重跑全部工具，不把原始草稿发给前端。

已核查安装源码：`output_cls` 在最终阶段调用 `generate_structured_response`，会额外生成结构化结果；失败可能只发 warning 后返回缺少结构字段的 output。**原生结构化输出不保证零额外调用，也不能替代 fail-closed 检查。** 正常最终阶段需将这次调用、一次修复上限和 token 消耗纳入预算。[框架 Agent API](https://developers.llamaindex.ai/python/framework-api-reference/agent/)

发布策略：工具/操作实时，首期最终答案校验后一次性交付；这仍是事件流，但不承诺正文逐 token。后续确需更低首字延迟，再设计完整 section 校验后发布，避免额外的增量 JSON parser 和无法撤回的错误内容。

## 9. 上下文压缩与记忆具体方案

### 9.1 单一 token 预算入口

ContextBuilder 接收模型能力配置：上下文上限、输出预留、tokenizer/估算策略、工具调用、结构化输出和视觉支持。未知模型使用显式配置的保守值，不按名字猜测无限上下文。

每次模型调用检查：

`系统提示 + 工具 schema + 当前用户输入 + 摘要 + 近期消息 + 本轮证据 + 输出预留 + 安全余量 <= 模型上下文上限`

- 使用框架 tokenizer/计数工具；与模型不匹配的 tokenizer 只作为估算，保留余量并记录其类型。
- 将已测量的固定输入从窗口扣除后设置 Memory 的有效预算，不直接把整个 32K 配给 history。
- 工具输出、图片和结构化修复调用均单独计入请求预算。整次运行累计 token/call 预算继续保留，语义独立。
- 删除应用 12 条/24,000 字符阈值，不与另一套隐式 Memory 共同裁剪。可保留数据库分页读取优化，但分页不能决定语义保留范围。

### 9.2 显式现代 Memory

- `agent.run(..., memory=memory)`，不依赖内部默认 ChatMemoryBuffer。
- 使用现代 `Memory` 的 token/flush 生命周期；将 SQL 工具调用与结果作为完整事务保留，避免切断配对。
- 按 `(user_id, conversation_id, workspace_id, scope_version)` 隔离 memory。会话展示保留旧消息，模型输入使用当前授权范围，摘要也必须按范围失效。
- 显式传入 chat store；不使用框架默认临时/随机 session store 作为生产持久化。接入应用数据库时表结构由 Alembic 管理，禁用/绕过运行时自动建表行为，或使用薄的仓储 adapter。
- 不并行向 memory.aset 传完整旧历史并恢复已存 checkpoint，避免初始化覆盖或重复追加。首次从权威消息构建，后续按游标增量进入。

### 9.3 一个有限的滚动摘要扩展

现代 Memory 提供 BaseMemoryBlock 扩展点，但没有在当前安装版本默认启用完整滚动会话摘要。设计**一个** SessionSummaryBlock，复用框架 flush 和 LLM/Pydantic 调用；自定义只负责摘要政策、消息范围和保存。

保留内容：用户目标、当前问题指代、已确认指标/维度/时间/单位/筛选口径、明确纠正、尚未完成事项、需要再次查询的结果引用。摘要不复制图表配置、全量行集、代码或长文档。

- 只总结上次摘要游标之后、被移出近期窗口的完整消息段，不每轮重总结整段历史。
- 摘要只在 token 压力或明确阶段边界产生；近期完整消息优先保留。给摘要配置独立 token 上限，避免摘要本身无限增长。
- 被取消/失败的工具不能总结成成功事实；用户的请求、模型推断和工具证据必须保留区分。
- 旧数值是“某次查询观察”，记录时间和结果 ID；后续问最新数据要重新查询，不能把摘要当作权威业务数据库。
- 普通摘要当作上下文数据注入，不可提升为系统权限或覆盖查询授权。系统规范/当前 scope 不参与模型自由总结。
- 摘要失败时保持上一次有效摘要，使用可容纳的近期完整消息；仍超预算则明确失败/要求缩小输入，不提交超限请求。

FactExtractionMemoryBlock 可用于明确的会话事实抽取，但不能额外再启用一套重复的滚动摘要/长期抽取策略。默认先只选择 SessionSummaryBlock；长期偏好保留现有少量字段，后续确有召回需求再评估内置事实/向量块。

### 9.4 摘要持久化与恢复

最小 checkpoint 保存：owner/scope key、summary、覆盖到的消息游标、Memory block 的必要状态、版本号和生成配置标识。完整聊天消息仍由原 Message 记录保存，chat store 的活动/归档记录是派生上下文，不形成第二个独立聊天真相。

- 通过原子游标比较/更新避免重试重复压缩；同会话仍保持一个活动 AgentRun。
- run 记录提交时的摘要版本和消息截止位置；worker 不因客户端切换而读到其他历史。
- 长任务需要 flush 时可保存运行级 memory checkpoint，只有确认的消息段推进会话级摘要游标。此 checkpoint 不承诺恢复整个 Agent 执行位置。
- 空间来源变更、消息删除/编辑或摘要配置不兼容时，从授权消息重建；旧摘要不跨 scope version 复用。
- 展示 Q1/S1 转成有 run/result/source version 的引用再进入摘要，防止下一轮编号重用。
- 不保存 API Key、完整提示草稿或无关工具原始日志到摘要对象。

### 9.5 工具输出是压缩重点

执行工具保存完整授权结果；返回给模型的视图按 token 预算包含 schema、结果引用、行数/截断信息、相关聚合值和必要样本。

- 小结果在预算内完整返回，大结果标记 preview/sample，不让模型把样本当全量统计。
- 新增按结果 ID 读取有限行/字段的工具时复用既有授权与 SQL 服务，不另建查询系统。
- 表格/图表 UI 从完整结果读取，模型不需要再看到所有展示数组。
- 检索证据按预算返回相关片段并保留来源和版本；不能仅保留来源 ID 而没有足够证据支撑结论。
- 删除旧工具结果正文时保留调用/结果配对和引用；当前仍需分析的证据不能在压缩中丢失。

## 10. 持久化调整与自定义逻辑清理

允许增加必要数据库字段/表，不为维持零迁移把所有内容继续塞进 `tool_calls`。

| 项目 | 目标处理 |
| --- | --- |
| Message | 增加版本化、有序 UI parts 展示快照；content 成为兼容/导出的派生文本 |
| 查询结果/资产 | 一个权威存储位置，UI parts 和 context 用稳定引用 |
| RunEvent | 保留有序执行记录；标准 wire 事件为明确投影，浏览器不消费内部诊断日志 |
| Session memory checkpoint | 保存摘要、游标、scope 和必要框架状态 |
| 旧消息 | 只在读取边界做一次兼容转换，不批量改写业务结论或补造历史建议 |

结果仓库首期可直接复用已持久化的 `RunEvent.query_result`，通过受权的结果读取接口按 run/query 定位；只有检索、保留周期或体积指标证明必要时才增加独立结果表。UI part 只带类型、稳定 ID、结果引用和少量显示配置，避免为了去重再建一套大数据存储。

具体删改清单：

| 当前逻辑 | 动作 |
| --- | --- |
| App 中双份 SSE 帧解析 | 删除，使用官方 client/decoder |
| App.applyRunEvent 的通用文本/工具聚合分支 | 删除，交给 runtime |
| 整份 appMessage 反向附着与手工 synthetic tool parts | 改为标准 parts + 小型业务 metadata |
| Message.tool_calls 混装状态/结果/答案 | 按上述权威记录与展示投影拆分 |
| render_answer 中 SQL 表格 Markdown 拼接 | 从 UI 路径删除；有导出需求则独立 serializer |
| 新消息每次 AST 清理、两端代码意图过滤 | 收敛到服务端校验；旧历史兼容单独保留 |
| prepare_chat 的固定条数/字符裁剪 | 删除，改 ContextBuilder + 显式 Memory |
| 原始工具行集无预算全部送入模型 | 改为预算受限证据视图 |
| 手工 raw JSON parse/展示兜底 | 改为框架结构化结果 + 业务校验，失败不显示草稿 |
| Recharts/shadcn/assistant-ui primitives | 保留与组合 |
| 权限、SQL policy、引用检查、worker/取消 | 保留 |

不以文件拆分数量或代码行百分比作为成功指标。关键是移除重复状态所有者和 parser，实现一个清晰的协议出口、展示投影和上下文入口。

## 11. 成熟度与依赖验证门槛

- 沿用 React 18/Tailwind 3；只升级满足 adapter 所需的兼容依赖，不整体切换技术栈。
- 上次核查的 AG-UI adapter/client 存在 0.x/1.x 版本范围差异，详见集成评估；该记录不是本次批准的锁定清单，实施前重新选择并锁定可兼容组合。
- AG-UI threadList 仍为 experimental；history/resume 需要应用 adapter。语义不符合时先使用稳定的公开边界，不能依赖私有运行时字段。
- 协议映射、媒体顺序、恢复和停止必须使用安装版本的测试/源码核对，不能照网页最新示例直接安装所有 latest。
- 任何自动显示 reasoning/thinking 默认关闭；业务操作步骤来自工具事件，保留默认折叠详情。
- native output_cls 缺失响应的错误处理、现代 Memory 的 chat-store/schema 管理，以及摘要恢复是必要验收项。
- 不新增第二套 UI/runtime 来做同一功能；AG-UI 和 AI SDK 只选择一个主 wire protocol，兼容窗口结束后删除旧协议。

## 12. 审核后的实施顺序

当前仅提交方案；以下阶段均尚未开始。

| 阶段 | 工作 | 完成条件 |
| --- | --- | --- |
| P0 架构与依赖验证 | 固定协议版本，验证 FunctionAgent→官方 runtime，比较恢复顺序限制 | 原生 parser/runtime 足以承载需求，不需自建消息聚合器 |
| P1 结果/parts 模型 | 建立统一结果引用和有序展示投影，旧历史 adapter | 多图/表格/图片顺序与历史一致，现有功能保留 |
| P2 通信替换 | 接入标准事件、history/resume、显式取消，删除双份解析 | 刷新/断连/切换/停止/幂等全部通过 |
| P3 上下文与摘要 | 显式 Memory、预算、结果视图、SessionSummaryBlock、checkpoint | 长对话保留约束，所有调用在预算内，恢复不重复摘要 |
| P4 生成与清理 | 原生结构化结果、业务校验、导出/朗读、移除旧分支 | 无源码泄漏、错误可见、兼容边界可清楚移除 |

协议层若验证失败：记录具体原因并采用 AI SDK UIMessage Stream 备选，再推进同一 parts/context 目标；不重新设计私有协议。

## 13. 审核后必须执行的验收

1. 文字、多个表格/图表、图片和来源按稳定顺序展示；刷新后顺序、数值和状态一致。
2. 用户不索要代码时，Python/Mermaid/JSON 草稿不进入正文；明确索要代码时可正确展示；未知 data part 不打印原始负载。
3. 开启建议严格三个，关闭为空；完成、历史恢复和点击追问一致，failed/partial 不伪装完整成功。
4. 工具 ID 和参数/结果正确配对；默认折叠操作详情；多次查询不覆盖之前图表。
5. 取消当前 run 后服务端进入真实终态；断连/切换不取消；停止 A 不影响 B；重连不重复执行 Agent。
6. 重复创建请求、重复/缺失事件、历史游标、半段工具参数恢复、终态重放均一致；快照/sequence 原子性成立。
7. 至少覆盖超过旧 12 条窗口的多轮问答：早期用户口径、后续纠正和指代在压缩后仍保留。
8. 中文/英文/长表格/长工具字符串、不同模型窗口、图片和多次工具调用都满足逐请求 token 预算；累计成本预算单独生效。
9. 摘要只覆盖新增淘汰段，模型调用次数可追踪；worker 重启不重复总结，失败/取消不变成已完成事实。
10. 空间版本改变、来源撤销、消息删除/编辑、跨用户访问时摘要与资产授权正确；摘要不替代查询证据。
11. 空结果、截断、负数饼图、不支持双 Y 轴/area、Decimal/大整数等按能力与精度规则展示。
12. 无视觉能力模型不接收图片后静默忽略；资产 URL 过期和读取失败可恢复或明确报错。

指标：维护中的 parser/reducer 数量、重复数据体积、重连重复率、每次请求上下文 tokens、摘要触发次数/耗时、工具 preview 比例、格式失败率、长对话约束保留率。先取得旧方案基线，再比较；本报告不虚构收益百分比。

## 14. 待审核结论

建议批准以下范围：

1. 采用标准通信和官方 runtime，主选 AG-UI，并设置有序内容/恢复语义验证门槛。
2. 统一消息 parts 与结果/资产引用，保留现有成熟渲染组件。
3. 用显式现代 Memory 和 token 预算替换字符裁剪，保留一个薄的持久化会话摘要扩展。
4. 保留业务校验、后台任务、用户/空间权限及精确数据链路。

这能降低通用通信和展示方面的自定义比例，同时补齐上下文能力。仍需保留的代码集中在本项目独有的业务规则与持久化适配，而不是另行实现一个聊天框架。
