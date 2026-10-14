# 下一步问题建议

更新日期：2026-10-12。

本功能已迁移到[统一回答协议](unified_answer_protocol.md)。最终回答、图表展示和建议问题的设计、取舍及验收以该文档为准。

## 当前行为

- `next_questions.is_enabled` 开启时，最终回答 JSON 的 `suggestions` 必须包含三个不同且非空的问题；关闭时必须为空数组。
- 与业务内容在同一次 Agent 最终生成中交付。协议无效时仅尝试一次格式修复；再次失败明确报告回答格式错误，不静默返回缺少建议的“完整成功”。
- 单个 `answer` SSE 事件传递完整对象。存入 `Message.tool_calls.answer`，前端从最后一条助手消息派生建议，实时与历史会话共用同一来源。
- 使用 assistant-ui 原生建议按钮发送追问。新问题发送后及任务执行期间隐藏上一轮建议；失败、停止或部分完成时不显示建议。
- 暂时兼容旧 `suggestions`、`done.suggestions` 事件及历史 `tool_calls.suggestions`；新生产流程不再使用正文定界符或单独的建议生成请求。
- 当前产品固定三条；`count` 的历史配置字段仍保留，暂不支持任意数量。

## 历史与运行

历史中未保存的建议不会自动补生成；不改写历史数据库。后端修改必须同步重启 API 和独立 worker，仅 API `--reload` 不会使 worker 重载。

## 实现入口

- `backend/app/agents/answer.py`：协议、校验、受控展示文本、历史代码块清理。
- `backend/app/agents/executor.py`：模型生成、一次修复及单一回答事件。
- `backend/app/application/chat.py`：事件持久化与执行终态。
- `frontend/src/App.tsx`：事件接收与从消息派生建议。
- `frontend/src/components/chat/Thread.tsx`：原生建议按钮。
