# 前端开发

开发规则见 [AGENTS.md](AGENTS.md)。项目使用 React、Vite、Tailwind CSS 和 shadcn/ui。

## 聊天职责

- `ChatRuntimeProvider` 使用 assistant-ui 官方 AG-UI runtime；运行时独占当前线程的实时消息状态。
- `useChatSession` 管理会话列表、当前会话、工作空间和模型选择。
- `Thread`、`Composer`、`MessageItem` 使用 assistant-ui 消息与输入 API。
- `chat-runtime.ts` 将归档消息投影为 runtime 展示对象，不解析流、不维护第二份消息历史。
- `BusinessAnswerPart` 根据共享展示类型渲染答案、查询表格、指标和图表。

## 开发和验证

```bash
npm ci
npm run dev
npm test -- --run
npm run build
```

开发端口为 5174，API 代理端口为 8001。系统职责和接口边界见根目录 [SQL Agent 重构说明](../docs/关系数据库_SQL_Agent问答链路分析与重构优化报告.md)。
