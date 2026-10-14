# assistant-ui 与 LlamaIndex 会话集成评估

日期：2026-10-13。范围：当前代码静态检查、官方文档与发布包源码核查。本轮仅形成报告，未修改业务代码、安装依赖或执行测试。

后续：通信、多媒体展示与上下文管理的完整目标方案见 [2026-10-14 重构提案（待审核）](ai_chat_refactor_proposal.md)。本文件保留为当时的集成核查记录。

## 1. 结论

**assistant-ui 可以接入 LlamaIndex，但当前没有查到直接消费 Python FunctionAgent 原生 `stream_events()` 的专用官方 runtime。已有可复用路径是 LlamaIndex → AG-UI → assistant-ui。当前项目没有使用这条路径。**

- assistant-ui 官方提供 `@assistant-ui/react-ag-ui` / `useAgUiRuntime`，处理标准事件和消息重建。[官方说明](https://www.assistant-ui.com/docs/runtimes/ag-ui/overview)
- LlamaIndex 官方发布 `llama-index-protocols-ag-ui`，提供 FastAPI 路由、Workflow 和 AG-UI 事件类型。[官方发布包](https://pypi.org/project/llama-index-protocols-ag-ui/)
- 这证明协议链路存在；本项目完整迁移的可行性仍需验证。官方 LlamaIndex 默认 Workflow 与现有 FunctionAgent、持久化 worker 不是同一种执行组织方式。

**建议目标：保留 Python LlamaIndex、后台任务和业务校验，将前后端会话事件逐步收敛到 AG-UI，由 assistant-ui 官方 runtime 管理消息。** 先做版本及持久化恢复验证，通过后替换自定义通信。现阶段不建议为了获得适配器而切换 Agent 框架或整体替换聊天 UI。

## 2. 当前实现

### 2.1 实际依赖

| 层 | 当前版本/方式 |
| --- | --- |
| UI | `@assistant-ui/react` 0.15.25，React 18.3.1 |
| UI runtime | `useExternalStoreRuntime`，应用自行持有 `messages` |
| Markdown | `@assistant-ui/react-markdown`，现有 Markdown/GFM 组件 |
| Agent | `llama-index-core` 0.14.25，`FunctionAgent` |
| LLM | `llama-index-llms-openai-like` 0.6.0 |
| HTTP | FastAPI，自定义 JSON SSE |
| 执行持久化 | 数据库 `AgentRun`、`RunEvent`、独立 worker |
| 未接入 | `react-ag-ui`、`react-data-stream`、`@assistant-ui/ai-sdk` |

代码依据：[前端依赖](../frontend/package.json)、[后端依赖](../backend/requirements.txt)。版本以工作区实际安装和配置为准。

### 2.2 请求与事件链路

1. `Composer` / 建议按钮通过 assistant-ui 调用 `onNew`。
2. `App.tsx:450` 的 `handleSend` 自行添加乐观用户消息、助手占位消息，POST `/api/chat/stream`。
3. `prepare_chat` 检查会话与业务空间、保存输入快照，创建 `AgentRun`；HTTP 返回 `run_started` 后订阅数据库事件。
4. 独立 worker 领取任务，`AgentExecutor` 调用 FunctionAgent 并遍历 `handler.stream_events()`。
5. 执行器转换原生事件，附加查询、图表、引用和最终回答事件；`persist_run_event` 同时写入事件日志和助手消息快照。
6. `App.tsx:166` 的 `applyRunEvent` 再次解释事件，更新应用消息状态。
7. `toRuntimeMessage` 把应用消息转换成 assistant-ui `ThreadMessageLike`；原始应用消息放在 `metadata.custom.appMessage` 中。
8. 历史通过 `/sessions/{id}/messages` 加载；未结束运行通过 `/runs/{id}/events?after_sequence=...` 恢复订阅。

关键代码：[App](../frontend/src/App.tsx)、[消息转换](../frontend/src/lib/chat-runtime.ts)、[HTTP 入口](../backend/app/api/chat.py)、[运行接口](../backend/app/api/runs.py)、[执行与持久化](../backend/app/application/chat.py)、[Agent](../backend/app/agents/executor.py)。

### 2.3 事件与 UI 对应关系

| 事件 | 当前用途 | UI 实现 |
| --- | --- | --- |
| `run_started` / `status` | 服务端 ID、排队/运行状态 | App 自定义状态和引用映射 |
| `tool_start` / `tool_end` | FunctionAgent 工具事件 | 自定义操作名称列表、WorkingIndicator |
| `query_result` | SQL、参数、结果行、查询引用 | 消息 metadata，折叠查询详情 |
| `tool_call` | 应用生成的指标/图表 | 转为合成 `render_metrics` / `render_chart` tool-call parts |
| `citations` | 知识检索证据 | 自定义引用按钮和详情弹窗 |
| `answer` | 经校验的最终答案、建议 | Markdown 正文与原生 Suggestions |
| `usage` | 用量估计 | 执行事件留存，正文不显示 |
| `error` / `done` | 错误和完成状态 | App 自定义更新，runtime 状态再次转换 |
| 旧 `chunk` / `suggestions` | 历史运行兼容 | App 仍接受，当前执行器不再产生 |

`tool_call` 在这里表示展示数据，并非 LlamaIndex 原生工具调用事件。真正的工具调用目前走另外两个事件类型。

### 2.4 已经复用的成熟组件

当前已使用 `ThreadPrimitive.Messages`、`MessagePrimitive.Parts`、Composer、Send/Cancel、Copy、Edit、Speech、Suggestions、Viewport、ScrollToBottom、`makeAssistantToolUI`；图表使用现有 Recharts 业务组件。需要重点简化的是 runtime 与应用状态之间的通信层。

执行过程当前默认折叠；展开后仍包含查询 SQL、参数、结果 JSON，以及懒加载的完整运行记录。原始工具结果不是正文，但用户仍可主动查看。编辑通过 `onEdit` 作为新问题追加，保持线性历史；未实现分支式编辑或助手 `onReload` 再生成。

## 3. 当前复杂度与限制

1. **两份 SSE 消费代码。** 首次 POST 与恢复 GET 各有一套 reader、TextDecoder、帧切分和 JSON 解析。它们适配当前服务端输出的 LF/单 data 行格式；不能作为完整的通用 SSE parser。恢复请求失败后主要记录日志，没有发现自动重连退避循环。
2. **两端都维护消息投影。** 后端 `persist_run_event`、前端 `applyRunEvent` 分别解释业务事件；随后又转换一次 runtime 消息。新增事件需要同步修改多个位置。
3. **运行状态有多种表示。** 数据库状态、App `isLoading` 与 refs、消息 `tool_calls.status`、assistant-ui status 共同维护。`partial` 目前转换为 runtime complete，而建议条隐藏；这是现有语义差异。
4. **实际工具调用没有完整进入 runtime。** 即时操作和消息快照只保留工具事件的 type/name；tool ID、参数、结果须另查 RunEvent，原生 tool-call 生命周期 UI 无法直接使用这些简略条目。
5. **展示结果只有单槽位。** 每个 `tool_call` 覆盖 `calls.chart` / `calls.metrics`；一轮多次查询不能在当前消息模型中独立保留多张图表。
6. **会话相关逻辑集中在 App。** App 共 740 行，同时管理模型、业务空间、认证后的数据加载、聊天请求、订阅、取消和会话切换。行数并非聊天代码的净规模，但表明关注点集中。
7. **最终文本并未逐 token 展示。** 当前主动丢弃 `AgentStream`，完成后校验 JSON，再一次性发出 `answer`。工具过程实时显示。这是为防止未经校验的绘图源码进入正文而采用的交付策略。

前两项及标准消息生命周期适合交给第三方 runtime；数据授权、业务空间和后台任务仍需要应用实现。仅把 App 拆成多个文件主要降低耦合，不等于消除自定义通信代码。

## 4. 官方方案核查

### 4.1 AG-UI：优先验证的迁移目标

assistant-ui 的 AG-UI runtime 支持文本、工具、状态和自定义事件，并有 history/speech 等适配槽。其多会话 threadList 接口仍标为 experimental；历史恢复需要应用提供 adapter。[官方 runtime 选项](https://www.assistant-ui.com/docs/runtimes/ag-ui/runtime-options)

本次另外只读下载了 **PyPI 0.5.0 wheel** 和 **npm 0.0.68 源码包** 到临时目录，未安装到项目。核查发现：

- LlamaIndex `router.py` 的 `get_ag_ui_workflow_router` 支持 `workflow_factory`；默认创建 `AGUIChatWorkflow`。
- `AGUIChatWorkflow` 自己执行 `astream_chat_with_tools`，默认允许并行工具调用；当前项目使用 FunctionAgent 且关闭并行调用。
- 路由传入 `input_data`，只转发包内定义的 AG-UI Workflow 事件；不是把任意 FunctionAgent 的原生事件自动转换为 AG-UI。
- 默认实现会发送 LLM 文本 delta 和消息快照。直接套用会把最终协议 JSON 或未经校验的文本送入 UI，必须保留当前发布前校验。
- 默认路由按 HTTP 请求启动 Workflow，源码中没有本项目的数据库队列、持久化游标重放、用户业务空间授权及取消接口。
- assistant-ui 已有 history `resume()` 接口；缺少该实现时，源码明确跳过运行恢复，避免重新执行 Agent。因此“支持恢复”不等于自动适配已有 `/runs/.../events`。

发布包来源：[LlamaIndex wheel](https://pypi.org/project/llama-index-protocols-ag-ui/0.5.0/)、[assistant-ui npm 包](https://www.npmjs.com/package/@assistant-ui/react-ag-ui)、[官方仓库](https://github.com/run-llama/llama_index/tree/main/llama-index-integrations/protocols/llama-index-protocols-ag-ui)。PyPI README 仍示范从 `server` 导入，本次 wheel 实际实现位于 `router.py`；后续以锁定发布包源码和导出为准。

#### 版本兼容发现

2026-10-13 直接读取 npm/PyPI registry 元数据得到：

| 包 | 核查版本 | 约束/说明 |
| --- | --- | --- |
| `llama-index-protocols-ag-ui` | 0.5.0 | core `>=0.14.1,<0.15`；ag-ui-protocol `>=0.1.15` |
| `@assistant-ui/react-ag-ui` | 0.0.68 | client `^0.0.59`、core `^0.3.27`、store `^0.3.19`；React 18/19 |
| `@ag-ui/client` latest | 1.0.2 | 与上述 client 依赖不在同一 semver 范围 |
| `@ag-ui/llamaindex` latest | 0.3.0 | peer client/core `>=1.0.0` |
| 工作区 assistant-ui core/store | 0.3.24 / 0.3.17 | 低于上述 adapter 依赖下限 |

当前 Python core 落在集成包声明范围内，这只是依赖兼容证据。**不能将三个 npm 包全部用 latest 安装后宣称已经兼容。** 优先验证通用 HttpAgent 与所选 AG-UI 事件集合，锁定 client/core/store/encoder 的组合；不必强制引入 `@ag-ui/llamaindex`。React 主版本无需因此升级。registry 来源：[adapter 元数据](https://registry.npmjs.org/@assistant-ui/react-ag-ui/0.0.68)、[client 元数据](https://registry.npmjs.org/@ag-ui/client/latest)、[LlamaIndex bridge 元数据](https://registry.npmjs.org/@ag-ui/llamaindex/latest)。

### 4.2 DataStream / Vercel AI SDK

`useDataStreamRuntime` 可消费标准消息流；assistant-ui 也有正式 AI SDK runtime。Python 服务可以实现对应 wire protocol，但仍要转换 LlamaIndex 事件，并接入持久化、停止和恢复。两个 runtime 的协议/版本不能混用。[DataStream](https://www.assistant-ui.com/docs/runtimes/custom/data-stream)、[AI SDK runtime](https://www.assistant-ui.com/docs/runtimes/ai-sdk/overview)

适合以文本和工具消息为主的系统。当前项目已经有后台运行、查询证据和状态同步，需要保留较多业务适配；本轮没有查到能直接包装现有 Python FunctionAgent 的官方 AI SDK 桥。为了 UI 适配引入 Node 代理和另一套模型调用层，收益较低。

### 4.3 AssistantTransport

官方提供 Python `assistant_stream` 和状态流协议，可表达任意 JSON 状态，但仍需要把应用状态转换成 UI 消息。其默认请求生命周期的取消与当前“断连后 worker 继续执行”的设计需要协调。[官方 AssistantTransport](https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport)

它更接近当前业务消息快照，适合作为 AG-UI 版本或生命周期验证不通过时的备选；不会自动消除现有后台队列和权限边界。

### 4.4 LlamaIndex Chat UI / 其他框架

LlamaIndex 自己的 `@llamaindex/chat-ui` 提供可组合组件，官方示例使用 AI SDK `useChat`；它并不会直接解决当前 Python 事件和后台队列的适配。[官方仓库](https://github.com/run-llama/chat-ui)

assistant-ui 已覆盖当前主要聊天组件。整体换 UI 会增加样式、语音、建议、业务空间、图表和历史迁移成本。LangGraph 也有专用 adapter，但切换 Agent 框架的成本超出当前通信重构目标。

### 4.5 方案比较

以下成本和适用性为基于当前代码的工程判断，尚未通过迁移原型测量。

| 方案 | 第三方复用程度 | 迁移成本 | 本项目建议 |
| --- | --- | --- | --- |
| 保持 ExternalStore，集中 SSE/client/reducer | 现有 UI；通信仍自定义 | 低 | 可作为过渡，主要降低耦合 |
| AG-UI + `useAgUiRuntime` | 标准 parser、消息聚合、工具状态、runtime | 中 | 优先验证、推荐目标 |
| AssistantTransport + Python assistant_stream | 状态同步/编码/runtime；仍需 converter | 中 | 备选 |
| DataStream / AI SDK runtime | 消息流、模型适配生态 | 中 | 可用，当前业务状态适配收益较小 |
| 全面换 LlamaIndex Chat UI / CopilotKit | UI/全栈能力更多 | 高 | 暂无充分收益 |
| 切换 LangGraph 等 Agent | 专用集成 | 高 | 不建议仅为会话 UI 切换 |

## 5. 建议的目标分工

### 5.1 保留业务执行层，增加单一标准事件出口

目标链路：现有 FunctionAgent → 回答校验/业务事件投影 → 持久化运行日志 → AG-UI 编码 → 官方 client/runtime → 现有聊天组件。

使用官方事件模型和编码器；有限的应用事件映射集中在后端。先保留 FunctionAgent，不直接启用默认 AGUIChatWorkflow。这样能保留工具预算、顺序执行、查询授权、上下文与错误处理。

| 现有概念 | 建议映射 |
| --- | --- |
| 任务领取/运行开始 | `RUN_STARTED`；排队信息置于应用 state |
| 工具开始/参数 | `TOOL_CALL_START` / `TOOL_CALL_ARGS`，保留稳定 toolCallId |
| 工具结束/结果 | `TOOL_CALL_END` 表示参数结束，实际结果用 `TOOL_CALL_RESULT`；展示内容按需裁剪 |
| 经校验的正文 | `TEXT_MESSAGE_START` / CONTENT / END，一次性交付也合法 |
| 图表和指标 | 标准 tool parts，按 query ID 区分，使用现有 tool UI |
| 建议与查询/引用证据 | 小型应用 state 或明确命名的 data parts，通过同一历史投影恢复 |
| 成功/失败/停止 | 按锁定版本的 RUN_FINISHED / RUN_ERROR 与状态/outcome 映射，不能一律作为成功结束 |

`TOOL_CALL_END` 不等同于工具执行结束，这是迁移时必须核对的协议语义。原始 SQL/工具结果只在折叠详情或受权详情接口展示，不作为 text message 发出。

### 5.2 交给官方 runtime 的职责

- 标准 SSE 事件解析、消息和工具 parts 聚合、runtime 状态。
- Composer、建议按钮、复制、语音、滚动及原生工具 UI。
- history adapter 的加载入口；会话切换接口采用时锁定版本。

预期删除 App 中两套 SSE 帧解析、通用事件到消息的 reducer，以及大部分手工 tool parts 拼装。效果需要以实际删除的重复分支和验收结果衡量，不预先承诺减少某个百分比的代码。

### 5.3 应用必须继续承担的职责

- 用户/业务空间权限、模型配置、数据源授权、只读 SQL、引用有效性。
- worker、任务租约、幂等创建、取消控制、RunEvent 顺序和重放游标。
- 三条建议的生成与校验、标题编号、真实表格、图表能力、显式代码请求意图。
- `/sessions` 与现有历史数据兼容，服务端保持消息权威来源；客户端传来的 history/state 不覆盖授权快照。
- 断连/切换只解除订阅，点击停止才取消后台任务。官方 `onCancel` 也可能在切换/卸载触发，不能无条件绑定服务端 cancel。
- `history.resume()` 连接现有运行；禁止用一次新的 POST 重新启动原任务。明确 run ID、assistant message ID、sequence 去重，以及重放工具参数时的累计方式。

协议迁移不能替代回答内容治理。AG-UI 可以忠实传递 Python、Mermaid 或最终 JSON，框架不会判断它们是否符合业务回答要求。现有 [统一回答协议](unified_answer_protocol.md) 应保留为业务校验层；前端旧消息清理最终可收缩为历史迁移兼容逻辑。

## 6. 实施顺序与验收条件

1. **兼容性原型。** 在隔离分支/目录锁定发布版本，验证 FunctionAgent 事件映射、官方 runtime 与 React 18、两条工具调用、经校验回答、图表及三条建议。当前报告未执行该原型。
2. **持久化语义验证。** 同一数据库任务支持刷新后续看、网络重连、切换会话不取消；显式停止才取消。验证重复帧、终态重放、仅恢复尾部工具事件和历史 message ID 对齐。此项不通过则暂不迁移主聊天链路。
3. **单一消息所有者。** runtime 管理 UI 消息；后端管理权威历史和任务。业务空间/模型状态留在应用，历史和恢复通过 adapter 接入，避免 App 再维护另一套完整消息 reducer。
4. **替换通信层。** 暂保留旧接口兼容，标准出口通过后删除双份 SSE 消费和旧 wire 分支；不长期并行维护两套实现。
5. **整理展示层。** 工具动作进入原生 tool UI，保留默认折叠；引用、查询证据、图表继续为业务组件。建议从统一消息/状态派生。

验收至少涵盖：普通问答、RAG 引用、多个 SQL/多张图、建议开关与历史恢复、格式修复成功/失败、partial/error/cancelled、停止后重放、切换空间/会话、权限隔离，以及绘图源码不进入正文。

当前结论的证据范围是代码、官方文档与发布源码。没有进行真实模型调用、协议端到端运行或依赖升级，因此报告不把“官方有 adapter”当作“本项目已完成适配”。
