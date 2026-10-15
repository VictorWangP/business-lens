# Agent 任务调度与执行生命周期技术设计

更新：2026-10-15。本文档阐明智能问数系统中基于 LangGraph 与异步中间件的“Agent 任务调度、执行流转与全生命周期状态控制”技术架构，涵盖状态机迁移、死循环防御、会话排他性锁、持久化 Checkpoint 与 Server-Sent Events (SSE) 流式恢复机制。

## 1. 业务目标与架构原则

- **确定性编排与状态持久化**：采用 LangGraph 构建可中断、可恢复的状态图拓扑。中间状态通过 `AsyncSqliteSaver` / 持久化 Checkpoint 存盘，保证系统重启或网络中断后能够精确定位断点。
- **单会话并发排他（Single-Active Run）**：通过数据库层面的条件唯一索引约束，确保单个会话内同一时刻最多只有一个任务处于活跃状态，杜绝并发竞争与上下文污染。
- **严格的执行边界与防死循环保护（Loop Guards）**：通过自定义 `ExecutionControl` 中间件，对模型调用次数、工具调用次数、重复工具调用进行严格计数与指纹去重。
- **优雅降级与最终总结（Final Answer Opportunity）**：当达到步骤或工具调用上限时，不简单暴力抛错，而是强制剥夺所有工具并注入总结提示，给予模型“基于已有事实输出最终答案”的最后机会。
- **流式推送与断点续传**：基于 `RunEvent` 序列号递增持久化，前端可通过 `after_sequence` 参数实现 SSE 流式断点续传。

## 2. 总体架构与状态流转

```text
[ 用户发起提问 ]
       │
       ▼ (POST /chat 或 POST /runs)
[ 1. 检查并创建 AgentRun ]
       │ 依赖局部唯一索引: status IN ('queued', 'running', 'cancel_requested', 'paused')
       │ 状态初始化: status = 'queued'
       ▼
[ 2. 异步 Worker 认领与租约锁定 ]
       │ 设置 lease_expires_at = now + 60s
       │ 状态迁移: queued ──> running
       ▼
[ 3. 构建 LangGraph 拓扑图与中间件 (AgentExecutor) ]
       │ 挂载:
       │  - TokenBudget (输入容量与预算限制)
       │  - ExecutionControl (循环守卫与工具调用计数)
       │  - ContextManagement (滑动折叠与早期历史摘要)
       ▼
[ 4. 执行循环与状态机迁移 ]
   ┌────────────────────────────────────────────────────────┐
   │ 循环步骤:                                               │
   │  Model Call ──> 工具调用判定 ──> 工具执行 ──> 结果回传   │
   │                                                        │
   │ 拦截规则:                                              │
   │  - 若工具指纹重复 >= 3 次 ──> 注入 REPEATED_TOOL_CALL   │
   │  - 若步骤达到 MAX-1 ──> 剥离工具，仅留 FinalAnswer 提示 │
   └────────────────────────────────────────────────────────┘
       │
       ├─ 正常结束 ────────────> status = 'completed', finished_at = now
       ├─ 用户主动停止 ────────> status = 'cancelled'
       ├─ 人机交互等待 ────────> status = 'paused' (GraphInterrupt)
       └─ 超出保护上限或异常 ──> status = 'failed', error = classify(...)
```

## 3. 数据模型与锁机制

由 `app/models/platform.py` 提供核心持久化表结构：

### 3.1 任务运行主表：agent_runs

| 字段名 | 类型 | 说明 | 约束 |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(36)` | 任务主键 UUID | PK |
| `user_id` | `VARCHAR(36)` | 所属用户 ID | FK -> `users.id`, 索引 |
| `conversation_id` | `VARCHAR(36)` | 所属会话 ID | FK -> `conversations.id` (CASCADE), 索引 |
| `workspace_id` | `VARCHAR(36)` | 当时业务空间 ID | 可空 |
| `scope_version` | `INTEGER` | 当时数据范围版本号 | 默认 0 |
| `resource_scope` | `JSON` | 绑定的数据源快照 | 默认 `{}` |
| `input_payload` | `JSON` | 用户提问及初始上下文 | 默认 `{}` |
| `assistant_message_id`| `VARCHAR(36)` | 绑定的最终助手消息 ID | 可空，索引 |
| `status` | `VARCHAR(30)` | 运行状态 | 默认 `'queued'`，索引 |
| `attempts` | `INTEGER` | 执行尝试次数 | 默认 0 |
| `lease_expires_at` | `DATETIME` | Worker 分布式租约到期时间 | 可空，索引 |
| `model` | `VARCHAR(100)` | 选用的基座模型标识 | NOT NULL |
| `error` | `TEXT` | 结构化错误信息记录 | 默认空字符串 |
| `created_at` | `DATETIME` | 创建时间 (UTC) | 默认当前时间 |
| `finished_at` | `DATETIME` | 完成时间 (UTC) | 可空 |

#### 关键约束：活跃会话排他局部唯一索引
```sql
CREATE UNIQUE INDEX uq_agent_runs_active_conversation 
ON agent_runs (conversation_id) 
WHERE status IN ('queued', 'running', 'cancel_requested', 'paused');
```
该索引从数据库底层彻底阻断“同会话多个 Agent 任务并发写入”，防止模型执行交叠导致消息上下文断裂。

### 3.2 执行事件流表：run_events

| 字段名 | 类型 | 说明 | 约束 |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(36)` | 事件主键 UUID | PK |
| `run_id` | `VARCHAR(36)` | 关联的运行 ID | FK -> `agent_runs.id` (CASCADE), 索引 |
| `sequence` | `INTEGER` | 事件序列号（单调递增：1, 2, 3...） | 联合唯一 `(run_id, sequence)` |
| `event_type` | `VARCHAR(30)` | 事件类型（`RUN_STEP`, `TOOL_CALL`, `TOKEN`, `DONE`） | NOT NULL |
| `payload` | `JSON` | 事件明细数据 | NOT NULL |
| `created_at` | `DATETIME` | 事件时间 (UTC) | 默认当前时间 |

## 4. 关键执行流控与中间件机制（ExecutionControl）

在 `app/agents/execution.py` 中，通过实现 `AgentMiddleware` 的生命周期钩子，实施细粒度保护：

### 4.1 重复工具调用指纹检测（Fingerprint De-duplication）

模型在未能获取预期数据时容易“换汤不换药”地重复执行同一工具。系统对每次工具调用计算内容摘要：
```python
fingerprint = hashlib.sha256(
    json.dumps([call['name'], call['args']], sort_keys=True, ensure_ascii=False).encode()
).hexdigest()
```
- 最近连续调用保留在状态列表中（最大保留 `AGENT_MAX_IDENTICAL_TOOL_CALLS`，默认 3 条）。
- 若连续出现相同指纹，中间件短路拦截，不再真实调用底层数据库，直接构造带错误码 `REPEATED_TOOL_CALL` 的 `ToolMessage`：
  > “调用没有进展或已达到工具上限。使用已有证据、调整参数或说明限制，不重复调用。”

### 4.2 临界上限优雅降级（Graceful Degradation）

当满足以下任一条件时，触发紧急降级路径：
1. `execution_model_calls >= AGENT_MAX_STEPS - 1`（步骤即将耗尽）。
2. `execution_tool_calls >= AGENT_MAX_TOOL_CALLS`（工具调用次数达到上限，默认 15 次）。

**处理逻辑**：
- 在 `awrap_model_call` 拦截器中，**动态剥夺请求中的所有可用工具定义**（`tools=[]`）。
- 在模型上下文中强制追加系统指令：
  > “本轮执行达到保护边界。禁止继续查询，只使用已有证据输出最终结构化答案；明确说明已完成内容、未完成事项和限制，不编造新事实。”
- 模型此时仅能调用 `SuggestedAnswer` 或输出纯文本；若模型仍尝试调用外部查询工具，系统直接抛出 `ExecutionLimitExceeded` 异常中断任务。

## 5. 接口与事件流式恢复（SSE）

### 5.1 事件流订阅与断点续传

- **路径**：`GET /runs/{run_id}/events?after_sequence=12`
- **实现**：
  ```python
  StreamingResponse(
      stream_run_events(run_id, after_sequence), 
      media_type='text/event-stream',
      headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
  )
  ```
- **工作机制**：
  1. 首先从数据库检索 `sequence > after_sequence` 的所有已存历史事件，以 SSE 规范格式批量推送。
  2. 若任务仍处于 `running` 状态，监听内存队列或 Pub/Sub 通道，实时流式推送新产生的事件。
  3. 收到 `RUN_FINISHED` 或 `RUN_ERROR` 事件后自动关闭流。

### 5.2 任务取消与抢占中止

- **路径**：`POST /runs/{run_id}/cancel`
- **逻辑**：
  - 若状态为 `queued` 或 `paused`，直接通过原子 CAS 操作更新为 `status='cancelled'`，并写入 `finished_at`。
  - 若状态为 `running`，将状态标记为 `status='cancel_requested'`；运行中的异步图在下一个节点轮询到该标志位后立即中断退出，并记录 `RUN_ERROR(code='CANCELLED')` 事件。
