# Agent 后台执行与多会话并发设计

> 状态：基础方案已实现。浏览器订阅与后台 Agent 执行已解耦，支持不同会话并发、事件续接和按 run_id 取消。步骤级 Agent checkpoint / 进程崩溃后恢复未实现。代码入口及后续约束见本文与 [Text2SQL 与关系数据库 Agent 查询设计](text2sql_agent_design.md)。

## 1. 目标与范围

用户提交问题后，Agent 任务应独立于当前浏览器页面和会话选择继续执行。用户切换到其他会话不取消任务；只有用户在对应任务上明确点击“停止”才请求取消。

本方案需支持：

- 会话 A 的任务运行期间，用户可以在会话 B 提交另一个问题；两个会话的任务可并行执行。
- 切换会话只改变界面当前显示内容和事件订阅，不改变后台任务状态。
- 切回某会话时，界面能恢复其消息、运行状态、最新进度和已产生的结果。
- 停止操作只影响指定的 `run_id`，不能误停其他会话任务。
- 同一任务的状态、事件和最终消息均由后端持久化；前端断线后可以按事件序号续接。

首期只保证“浏览器切换、关闭订阅或短暂断线不取消任务”。后台进程崩溃时从任意 Agent 步骤继续执行属于另一层能力，不作为首期保证。首期建议同一会话最多一个活动任务，以免并发回答顺序和上下文定义含糊；不同会话之间允许并发。

## 2. 修改前实现与根因

修改前，Agent 使用 LlamaIndex `FunctionAgent` 执行工具调用循环；工具、资源权限、执行预算、证据收集和业务任务生命周期由应用代码实现。具体入口见 `backend/app/agents/executor.py`。

修改前，`POST /api/chat/stream` 返回的 SSE 响应直接驱动 Agent。浏览器请求一旦被取消，后端流生成器收到 `asyncio.CancelledError`，将运行标记为 `cancelled` 并保存已产生的部分信息。前端切换会话时会中止全局 `AbortController`。因此，任务生命周期实际上绑定在当前 SSE 连接上。

项目已有 `AgentRun` 和 `RunEvent` 数据模型，事件会带运行 ID 和序号；`GET /api/runs/{run_id}` 可以读取一次性执行快照。项目也有数据库轮询 worker 和可选 Celery + Redis 依赖，但修改前 worker 处理文档导入及维护，不执行 Agent 任务。前端此前以全局 `isLoading` 和单个 abort controller 表示运行状态。

## 3. 建议的分层

保持现有 LlamaIndex `FunctionAgent` 和业务工具不变，新增任务调度与事件订阅边界：

```text
前端提交问题
  → API 保存输入快照并创建 AgentRun(queued)
  → 任务调度器投递 run_id
  → 独立 Worker 执行现有 LlamaIndex Agent
  → Worker 按序持久化 RunEvent，并保存最终助手消息与终态

前端订阅 GET /runs/{run_id}/events?after_sequence=N
  ← 从 RunEvent 重放缺失事件，再持续接收新事件

前端切换会话：关闭当前事件订阅；任务继续运行
用户点击停止：POST /runs/{run_id}/cancel；Worker 取消该次 Agent
```

SSE 连接是任务状态的读取通道，不再是 Agent 的执行容器。断开 SSE 不应改变 `AgentRun.status` 或触发 `handler.cancel_run()`。

## 4. 任务状态与执行规则

建议状态机：

| 状态 | 含义 | 允许的后续状态 |
| --- | --- | --- |
| `queued` | 已持久化，等待 Worker 领取 | `running`、`cancelled`、`failed` |
| `running` | Worker 正在执行 Agent | `cancel_requested`、`completed`、`partial`、`failed` |
| `cancel_requested` | 用户明确请求停止，Worker 尚未完成取消 | `cancelled`、`failed`、`completed` |
| `completed` | Agent 正常完成 | 终态 |
| `partial` | 有工具或步骤错误，但 Agent 给出部分结果 | 终态 |
| `failed` | 任务未能得到有效回答或 Worker 故障 | 终态 |
| `cancelled` | 用户明确停止任务 | 终态 |

取消接口必须验证当前用户对 `run_id` 的所有权。运行中的取消请求持久化为状态或标记，由 Worker 在事件循环、工具边界及可行的模型流边界检查；Worker 再调用 LlamaIndex handler 的取消机制。取消延迟受模型供应商请求中断能力及检查间隔影响。页面切换、页面卸载、SSE 断开和重新连接均不是取消请求。

终态更新、最终助手消息及最终证据快照应以事务方式提交，避免 UI 看到任务已完成但历史回答尚未保存，或任务已取消但仍显示运行中。

## 5. 输入快照、范围与消息顺序

任务必须执行提交时确认的内容，而不是 Worker 开始时可能已变化的前端状态。创建运行时需持久化或可稳定引用：

- 用户问题、会话 ID、用户 ID、业务空间 ID、空间版本和本次资源范围快照。
- 本次模型 ID / 配置引用，以及生成历史上下文所需的消息快照或不可变版本。
- 运行预算及需要固定的执行选项。

API Key 等供应商凭据不得以明文写入队列消息或事件。Worker 通过当前用户的受保护模型配置引用读取凭据；配置版本变化、删除或凭据失效时应明确让该任务失败并记录安全错误，不得回退到其他用户或其他模型的凭据。

不同会话的任务互相隔离，运行中不重新读取其他会话的上下文。首期对同一会话实行单活动运行约束：若该会话仍有 `queued`、`running` 或 `cancel_requested` 任务，拒绝或暂缓新的提问，并给出明确提示。后续若要支持同一会话并行，需先定义消息排序、历史快照、回答插入位置及后续提问是否等待前序结果。

## 6. 事件持久化与续接

`RunEvent` 是某次运行的有序事件日志，至少保留 `run_id`、单调递增的 `sequence`、`event_type`、负载和创建时间。现有事件类型可继续使用：`run_started`、`tool_start`、`tool_end`、`query_result`、`tool_call`、`citations`、`usage`、`chunk`、`error`、`done`。

事件写入应由 Worker 完成，再由 SSE 路由读取。订阅接口需支持 `after_sequence`：先按序返回已持久化但客户端未收到的事件，再等待和返回新事件。序号应由数据库安全分配，不能只依赖某个进程内计数器；重投、并发 Worker 或恢复流程不得生成相同序号。最终状态通过运行资源接口提供，也应有对应终态事件。

查询接口继续检查 `run_id` 所有权。返回任务详情和事件不能泄露其他用户的查询行集、文档内容、模型配置或执行记录。

## 7. 多会话并发和前端状态

每个活动任务以 `run_id` 独立执行，事件以 `run_id + sequence` 隔离。会话 A 的取消标记、工具事件、查询结果、回答和错误不能修改会话 B 的任务。

Worker 并发数是显式配置的容量上限。不同会话可同时占用不同执行槽位；槽位满时新任务保持 `queued`。需考虑模型供应商并发限制、数据库连接数、SQL 超时、内存和 token 预算。默认数据库 Worker 可使用有界并发；可选 Celery Worker 使用受控并发数。避免无上限创建 `asyncio` 任务。

前端应将运行状态按会话或 `run_id` 管理，不再依赖全局 `isLoading` / 单个 `AbortController`：

- 当前会话有活动任务时显示该任务的工作状态，并提供针对该 `run_id` 的停止按钮。
- 当前会话没有活动任务时仍可提交其他会话问题。
- 会话列表可选显示运行中标记；进入会话时加载历史消息和活动运行，并从最后已知序号订阅。
- 切换时关闭当前 SSE 订阅并保留其最后序号；切回后重新订阅。重复事件按序号去重，发现序号间隙则补拉缺失事件。
- 页面本地运行状态丢失时，以服务端 `AgentRun` 和 `RunEvent` 为准恢复。

## 8. 调度选型与框架边界

建议复用现有后台任务基础设施，按部署形态选择调度适配器：

1. 本地和单机默认部署使用应用数据库中持久化的 `AgentRun` 队列，由现有数据库 Worker 原子领取任务。领取条件需包含状态检查和租约/超时恢复，多个 Worker 不能同时成功领取同一个运行。
2. 多 Worker 部署可启用项目已有的可选 Celery + Redis 适配器。数据库中的 `AgentRun` 仍是业务状态和事件的权威来源；Celery 负责投递 `run_id`。需要有周期性扫描或 outbox 恢复，覆盖“数据库已提交但消息尚未投递”的窗口，并通过原子状态领取避免重复执行。
3. 队列投递和 Worker 重试需区分“任务消息至少一次投递”和“Agent 业务效果恰好一次”。Worker 必须幂等领取；只有明确设计重试安全和事件续号后，才能自动重跑整次 Agent。

当前 Celery 依赖是可选的，现有 Celery 任务主要处理文档导入；启用该适配器需要集成 Agent 运行任务、取消信号、恢复扫描、并发配置及部署验收。默认本地 Worker 顺序执行，也需扩展为有界并发。

首期不建议迁移到 LangGraph。LangGraph checkpointer 可在显式工作流步骤间保存和恢复状态，适合后续需要步骤级故障恢复、人工审批/暂停或确定性状态机的场景；但它不替代应用后台 Worker、用户级运行记录、取消授权和前端事件续接。单纯解决页面切换导致的断连取消，保留 LlamaIndex 并解耦 Worker 与 SSE 更小、更贴合现有代码。若未来 Agent 控制流变成复杂、多阶段且需跨进程恢复，再比较 LangGraph、LlamaIndex Workflow/Deploy 等方案及其运维成本。

## 9. 故障、恢复与重试边界

- 浏览器断开或切换会话：任务持续执行，事件留存，前端可续接。
- API 重启：已提交任务仍在数据库队列中，Worker 可继续领取；任务执行和事件查询由 Worker 与 API 分离。
- Worker 在运行期间崩溃：首期可依据租约将任务转为 `failed` 并提供重新执行入口。自动从中断的 Agent 工具调用处继续，需要保存 Agent 内部状态和副作用边界，不应仅凭事件日志假设可恢复。
- 用户明确停止：取消请求持久化，Worker 确认后将运行终态设为 `cancelled`。取消不可达时需由超时与状态协调逻辑处理并暴露真实状态，不能静默显示已停止。
- 重试时应启动新的执行尝试或明确标记 attempt；已持久化事件不能与新执行混成一个无区分的序列。业务查询是只读的，但模型调用、工具结果及消息写入仍需考虑重复成本和一致性。
- 终态运行不能被普通事件订阅或页面切换重新激活；显式“重新运行”应创建新的 `run_id` 并保留原记录。

本方案保证客户端生命周期独立，不承诺 Agent 步骤级崩溃恢复。要提供更强的进程故障恢复，需要另行设计 checkpoint、工具副作用幂等、attempt 和恢复验收。

## 10. 实施状态

| 阶段 | 工作 | 验收重点 |
| --- | --- | --- |
| 阶段 | 状态 | 已实现内容 |
| --- | --- | --- |
| P0：模型与状态 | 已实现基础 | AgentRun 保存输入快照、助手占位消息 ID、attempt 与 Worker lease；同一会话有活动运行时拒绝新提问 |
| P1：后台执行 | 已实现 | 默认数据库 Worker 独立运行 Agent；SSE 只订阅持久化运行事件 |
| P2：事件订阅 | 已实现 | 支持 `after_sequence` 续接、用户级鉴权和运行级取消接口 |
| P3：多会话 UI | 已实现基础 | 前端按活动会话恢复状态；切换只关闭订阅；不同会话任务可同时运行 |
| P4：并发与队列扩展 | 已实现基础 | 本地 Worker 有界并发；可选 Celery 任务投递 AgentRun 并周期恢复排队任务。自动从 Agent 内部步骤 checkpoint 恢复尚未实现 |

## 11. 代码入口

| 文件 | 职责 |
| --- | --- |
| `backend/app/application/chat.py` | 创建任务输入快照、Worker 领取、LlamaIndex 执行、事件持久化与 SSE 事件查询 |
| `backend/app/api/chat.py` | 创建 AgentRun 并返回订阅流；Celery 模式下投递 run_id |
| `backend/app/api/runs.py` | 运行详情、按序号 SSE 续接及指定运行取消 |
| `backend/app/workers/local.py` | 默认数据库队列的有界 Agent 并发、租约续期和过期运行恢复 |
| `backend/app/workers/tasks.py` | 可选 Celery AgentRun 任务、队列恢复派发及 Worker 并发配置 |
| `backend/migrations/versions/0007_agent_background_runs.py` | AgentRun 输入快照、助手消息关联、attempt 和 lease 字段 |
| `frontend/src/App.tsx` | 按会话订阅、断开与续接 SSE、应用运行事件和发送取消请求 |

实现并发上限通过 `AGENT_WORKER_CONCURRENCY` 配置，默认值为 5。升级数据库需执行 Alembic head（本地可运行 `backend/scripts/prepare_local.py`）。

## 12. 验收场景

1. 会话 A 提交问题后立即切换到 B；A 的 `run_id` 保持 `running`，不会收到取消状态。
2. A 运行期间在 B 提交问题；在容量允许时 A、B 均为 `running`，事件序号及结果分别归属于各自 `run_id`。
3. 在 A 和 B 间来回切换，两个会话都能看到正确的工作状态、查询证据和最终回答；切换不重复追加消息。
4. 停止 A 后 A 进入 `cancelled`，B 继续运行；以其他用户身份读取或停止 A 返回未授权/不存在。
5. 订阅中断后用最后序号重连，所有持久化事件按顺序补齐；终态运行重新打开仍显示最终状态。
6. Worker 并发数为 1 时第二个任务排队；提高并发数后不同会话可以同时运行；同一会话第二个活动任务按首期约束被拒绝或排队。
7. 用户范围、空间版本、模型引用和历史上下文在提交时固定；运行期间更改空间或切换会话不会改变已有任务权限。
8. Worker 领取竞争、重复队列投递、取消与完成竞争、Worker 崩溃租约回收及事件序号唯一性均有自动化覆盖。

## 13. 后续产品与运维约定

以下内容不影响已实现的页面切换与后台运行核心链路；需要扩展产品行为或增强运维能力时再明确：

- 超出 Worker 并发容量时，界面显示排队位置、预计等待或仅显示“排队中”。
- 用户删除仍有活动任务的会话时，是先取消并等待终态再删除，还是阻止删除。
- 用户退出登录或权限被撤销时，任务是否继续运行（建议已提交任务继续，结果仍按原用户鉴权隔离）。
- 同会话首期是拒绝新提问还是允许排队；无论采用哪种方式，都应避免两个 Agent 同时基于相同历史生成并发答案。
- 活动运行、事件和完整查询行集的保留时长，以及用户删除会话时对应运行事件的清理策略。

## 14. 官方参考

- [LlamaIndex Agent](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/)：现有 Agent 工具调用实现所使用的框架。
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：checkpointer、thread state 与持久化执行能力。用于判断何时需要步骤级状态恢复，不作为任务队列的替代。
- [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)：任务投递、确认、重投及幂等处理的官方说明。Celery 的投递语义不能替代应用侧 `AgentRun` 状态和事件日志。
