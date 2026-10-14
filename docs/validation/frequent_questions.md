# 常问问题实施与验证

日期：2026-10-12（Asia/Shanghai）。

## 实施结果

- Alembic `0004_frequent_questions`：`question_groups`、`question_records`、消息唯一键、级联删除及查询索引。旧聊天数据保留，旧静态常问配置不参与统计。
- 聊天事务同时保存用户消息与 pending 记录，模型统计不阻塞聊天流。
- `python -m app.workers.frequent`：独立于文档队列，单机共享存储文件锁保障单实例，顺序消费，重启恢复 processing，最多尝试三次。
- 精确匹配只归一化空白；相对日期绕过捷径。非精确匹配一次 Embedding + 内存余弦 Top 3 + 一次 LLM 资格/同义判定，严格校验 JSON 和候选 ID，模型调用位于 SQL 写事务外并设置超时。
- 读取接口按用户、资源范围聚合 completed 记录，默认三次展示，按次数与最近时间排序，最多十条。
- 前端每五秒、进入聊天、资源切换和回答结束刷新；显示真实次数，点击填入输入框，由用户提交。
- 设置只提供自动常问开关和正整数阈值；模型配置变化时提示重置，重置仅清除当前用户常问记录与分组。
- 完成写入前取得记录写锁并重检状态、资源与开关；关闭、重置、删除与模型调用并发时不会恢复失效任务。

## 自动化验证

```bash
cd backend
venv/bin/python -m pytest tests -q --disable-warnings
```

后端：97 passed，2 skipped（最终代码版本）。跳过的是未配置外部 PostgreSQL 的集成测试；SQLite 默认路径已验证。新增常问测试覆盖同事务入队/回滚、重复消息、精确匹配免模型调用、用户和资源隔离、Top 3、相对时间、资格跳过、三次失败、非法候选、worker 恢复与单实例锁、会话/消息/用户删除、列表排序与十条上限、代表问题保留、关闭期间不补算、调用途中关闭/重置及模型变化后的重置恢复。

```bash
cd frontend
npm run build
npm test -- --reporter=dot
```

前端：构建通过，36 tests passed。新增验证覆盖显示真实次数、点击填入且不自动发送、资源变化时清空旧列表并丢弃迟到响应、五秒刷新、回答完成刷新、阈值修改刷新、关闭时停止轮询，以及正整数阈值校验。原有聊天 SSE、停止、编辑、模型设置等回归测试通过。

现有 Pydantic/datetime 弃用提示以及前端打包体积提示仍存在。

本地 SQLite 已通过 `scripts/prepare_local.py` 备份并升级至 `0004_frequent_questions`。Docker Compose 与 README 均已加入独立常问 worker。此验证未向本地业务会话写入测试消息。

## 真实模型语义验收

`backend/tests/fixtures/frequent_questions.json` 包含 28 组人工标注样本：同义改写，地域/年份/指标/排序/Top N/边界/数值/否定/单位/型号/筛选范围差异，呈现方式，退款条件与操作，寒暄及省略追问，跨年、跨月与跨日的相对时间。

```bash
cd backend
venv/bin/python scripts/validate_frequent.py \
  --user-id <已配置对话及嵌入模型的用户ID> \
  --output ../docs/validation/frequent_questions_live.json
```

脚本只读取用户模型配置，将公开样本发送给配置的模型接口，在内存完成向量排序与判定并输出逐项报告，不修改应用数据。可加 `--retry-failed` 仅重试失败项，保留已通过项及失败项的尝试记录。`--concurrency 3` 可并发验证彼此独立的样本（生产 worker 仍顺序处理）；接口异常最多重试三次，语义误判不重试，避免用重复调用掩盖分类错误。

用户已于本次验证中明确授权向配置的阿里云接口发送样本。使用模型 `qwen3.7-flash` 与 `qwen3.7-text-embedding-flash`。

首轮真实验证发现：模型有时输出非 JSON 文本，且把“完整但不匹配候选”的问题误判为 eligible=false。首轮 28 项中 10 项通过，完整链路在“不同指标建立新组”处失败，原始报告保留为 `frequent_questions_live_initial.json` 和 `frequent_questions_e2e_initial.json`。

已在生产判定调用中启用 JSON 对象输出模式，并明确资格判断独立于候选匹配、模型能否回答及是否有数据，增加完整但不匹配/无候选等示例。随后复验还发现相对时间相同文字的跨年/跨月/滚动窗口误合并，已补充新问题和候选各自独立的上海时区 year/month/local_date/yesterday 上下文，并要求先解析时间范围再比较。严格 JSON/候选 ID 校验仍保留。新增模型调用边界回归测试验证 JSON 模式、提问时区及 eligible=true/matched_group_id=null 的处理。

最终提示词复验结果：**28/28 项通过**，包括跨年“今年”、跨月“本月”、昨天与绝对日期、跨月的过去七天等时间样本。最终这一轮所有样本均一次调用成功，无接口异常重试。

报告：[frequent_questions_live.json](frequent_questions_live.json)。中间一轮报告保留为 `frequent_questions_revised.json`（24/28 通过，含一次接口超时和三项时间误合并），便于核对修复前后结果。最终样本全部按最终代码重新调用，没有沿用旧提示词的通过结果。这是小样本开发验收，不代表所有自然语言问题的准确率。

## 真实完整链路验收

```bash
cd backend
venv/bin/python scripts/validate_frequent_e2e.py \
  --user-id <已配置阿里云对话及嵌入模型的用户ID> \
  --output ../docs/validation/frequent_questions_e2e.json
```

该脚本只读取现有模型配置，在新建的临时 SQLite 库中执行 Alembic 迁移、应用 lifespan、真实聊天 HTTP/SSE 路由和真实独立常问 worker 子进程，不替换模型或流式聊天实现。完成后终止测试 worker 并删除临时库及存储，保留脱敏报告。

最终代码版本再次完整复核：**44/44 项检查通过，9/9 次真实模型聊天流正常完成**。报告：[frequent_questions_e2e.json](frequent_questions_e2e.json)。

覆盖：

- 三种独立同义问法通过真实 Embedding/LLM 归入一组，前两次不展示，第三次显示 count=3，保留首次问法。
- 将展示的常问代表问题再次提交，产生新的 SSE 回答，count=4；重复处理相同 message_id 不增加次数。
- 不同指标建立独立组，寒暄跳过，用户与知识库范围不混用，资源越权聊天返回 403。
- 关闭期间的提问有正常 SSE 回答，但不入统计队列；重新开启不补算。
- 删除两条会话后，次数依次降至 3、2，低于阈值后隐藏。
- 重启真实 worker 子进程，将中断状态 processing 的记录恢复并完成，attempts=2，计数无重复。
- 重置清空当前用户分组及统计记录，聊天消息仍在。

此端到端脚本通过 ASGI HTTP 传输调用真实路由，验证后端和外部模型的完整链路；前端菜单点击、输入框填入、轮询及资源切换由前述 36 项前端测试覆盖。
