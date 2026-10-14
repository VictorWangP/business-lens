# 反馈管理实施与验收

日期：2026-10-13。状态：基础版已实现，本地 SQLite 已升级并完成验收。

设计入口：[反馈管理设计](../feedback_management_design.md)。

## 已实现

- 聊天助手回答的错误反馈，原因及说明验证、提交去重、提交后状态展示及历史会话恢复。
- 回复校对列表，问题/用户/状态组合筛选、服务端分页、按反馈时间倒序、空状态与失败重试。
- 处理弹窗，原始问答、图表、表格、指标、引用、查询依据和上下文快照；两状态、内部备注、处理历史。
- 已处理必填备注、带新说明重新打开、乐观锁、冲突保留草稿、网络异常后保存结果核对。
- 显式 feedback_admin 权限、服务端逐请求检查、撤权清除管理页面、身份切换清除摘要缓存。
- `0008_answer_feedback` 数据库迁移、SQLite 升级/回退/再次升级、反馈级联与 SET NULL 生命周期。
- 原消息/会话删除后保留反馈证据，删除操作者保留姓名快照；会话删除提示说明快照仍保留。

## 自动化检查

| 检查 | 结果 |
| --- | --- |
| `backend/venv/bin/python -m pytest backend/tests -q --disable-warnings --tb=short` | 148 passed，2 skipped |
| `npm --prefix frontend test -- --reporter=dot` | 15 个文件、68 项通过 |
| `npm --prefix frontend run build` | TypeScript 与 Vite 构建通过 |
| `git diff --check` | 通过 |

后端新增反馈测试覆盖完整闭环、普通用户及跨用户越权、参数伪造、实时撤权、字面通配符搜索、分页、运行资格、历史关联歧义、快照大小上限、并发重复提交、并发更新、审计失败回滚、删除原会话、删除处理人、原始范围及不可变快照。

前端新增测试覆盖提交及失败保留、其他原因必填、会话切换隔离、未完成回答隐藏入口、弃改确认、完成备注校验、版本冲突显式重新加载、搜索分页、撤权，以及登录刷新/旧账号迟到响应不覆盖新账号等。

全量回归发现并修正两处旧测试适配：资源范围测试从旧的 prepare_chat 元组/stream_chat 调用改为现有 AgentRun 输入快照和后台执行；语音测试显式模拟安全上下文，并新增非安全上下文拒绝麦克风访问的校验。没有为通过测试改变上述业务行为。

两项跳过均为既有 PostgreSQL 集成测试：未设置 `RAG_TEST_POSTGRES_URL`。新功能尚未在实际 PostgreSQL 实例运行验收。已有 datetime/Pydantic 弃用提示与 Vite 大包体积提示保留，不影响本次测试/构建结果。

## 本地运行结果

- 迁移前确认活动 AgentRun 为 0。
- 使用 SQLite backup API 保存 `storage/app.db.backup-feedback-20261013T025713Z`，文件权限 0600。
- 当前本地数据库迁移至 `0008_answer_feedback`，`PRAGMA foreign_key_check` 返回空。
- 按用户明确选择，将 `admin`（UUID `7b8da0a9-a6fa-4d4d-aa2d-7a9ae34a6b22`）设置为 feedback_admin；其他账号未授予该权限。
- 真实本地开发服务 `/api/health`、`/api/auth/me`、`/api/feedback` 均返回 200，角色与迁移版本正确。此检查只读，真实数据库中未新增验收反馈。记录：[api-smoke.json](feedback/api-smoke.json)。

页面刷新或重新登录后，admin 可见“反馈管理 → 回复校对”。普通账号只在自己回答处提交反馈、查看状态。

## 浏览器验收

在临时 SQLite、独立 8001/5174 端口运行真实前后端，使用临时验收账号，未修改真实用户的回答、会话或反馈内容。

已核对：

1. 从聊天回答打开反馈弹窗，填写说明并提交；显示成功提示，按钮变为“已反馈 · 待处理”。
2. 列表新增反馈；打开处理弹窗，选择已处理、填写备注后确认；列表状态、处理人、时间、版本与历史正确恢复。
3. 图表、指标、Markdown 表格与原始正文可见；来源依据可展开，长内容滚动时取消/确认按钮保持可达。
4. 明亮和暗色主题正常；390×844 窄屏使用单栏。修复弹窗横向溢出后，实测弹窗宽 351px、左右边界 19.5/370.5px，无横向溢出；键盘可进入备注和处理历史。
5. 将真实本地数据库中已完成的一条 SQL 回答复制到隔离环境，上报后核对正文及两次查询的 SQL/参数/结果行/截断标识均与持久化原始记录一致。没有新模型调用，也没有修改真实数据库的消息。记录：[persisted-sample.json](feedback/persisted-sample.json)。这是既有模型回答的证据保真验证，不代表重新验证模型业务结论正确。

截图为隔离验收环境，列表中的测试反馈不代表真实本地管理员已有待处理事项。

- [列表：明亮主题](feedback/list-light.jpg)
- [处理弹窗：明亮主题](feedback/process-light.jpg)
- [处理弹窗：暗色主题](feedback/process-dark.jpg)
- [处理弹窗：窄屏](feedback/process-mobile.jpg)
- [提交反馈：暗色主题](feedback/submit-dark.jpg)
- [真实历史 SQL 回答的隔离副本](feedback/persisted-sql-sample.jpg)

## 10 万条反馈基准

复现命令（只使用可自动清理的临时数据库）：

```bash
backend/venv/bin/python backend/scripts/benchmark_feedback.py --rows 100000 --samples 20 --output /tmp/feedback-benchmark.json
```

| 场景 | P50 | P95 |
| --- | ---: | ---: |
| 首页 | 2.03ms | 2.24ms |
| 问题 + 用户 + 状态组合搜索 | 53.14ms | 69.19ms |
| 无结果文字搜索 | 136.09ms | 139.13ms |
| 深分页 | 3.81ms | 4.69ms |

每场景 20 次，额外一次预热，包含鉴权/查询/序列化，采用 SQLite 3.53.1、模拟问答证据及 ASGI 进程内传输。结果达到设计的 500ms 目标。测量不含真实网络、多人并发和其他应用负载，不代表所有部署环境的性能承诺。原始结果：[benchmark.json](feedback/benchmark.json)。

## 运维

新增接口由 API 进程加载，不需要额外反馈 worker、模型调用或第三方服务。管理员授权/撤权命令见 README；迁移前需备份。若回退到 `0007_agent_background_runs`，会删除反馈表及角色字段，应先导出需保留的数据。

本期不提供用户撤回、公开回复、批量处理、自动修正答案或多组织租户隔离；这些范围与已审核设计一致。
