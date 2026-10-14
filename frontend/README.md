# 前端开发

开发规则见 [AGENTS.md](AGENTS.md)。保留 React 18、Vite、Tailwind CSS 3，通用 UI 使用 shadcn/ui。

## 会话

- `ChatRuntimeProvider`：官方 `HttpAgent` + `useAgUiRuntime`；history adapter 恢复归档，官方 runtime 独占实时消息状态。
- `Thread/Composer/MessageItem`：原生消息、输入、建议、编辑、复制、语音与滚动组件。
- `BusinessAnswerPart`：命名 data part 映射 Recharts、指标和 shadcn Table，未知 part 不展示原始 JSON。
- `InterruptPrompt`：官方 interrupt/resume hooks；业务澄清输入。
- `chat-runtime.ts`：产品归档与原生 parts 的只读投影，不解析流、不聚合实时消息。

编辑问题使用原生编辑 Composer，再通过公开 append API 作为新问题发送，保留既有对话。切换会话只取消订阅；停止按钮显式请求服务端取消。

菜单和产品功能保留业务空间、数据、知识库、模型配置、收藏、常问、反馈管理和语音。语音适配器负责服务端 ASR 与浏览器朗读，配置和切换时释放资源。

## 开发和验证

```bash
npm ci
npm run dev
npm test -- --run
npm run build
```

开发端口 5174，API 代理 8001。测试使用实际官方 runtime、原生组件和 Recharts，外部 HTTP/模型替换为测试边界。完整方案与验收见根目录 README 及 `docs/langgraph_implementation.md`。
