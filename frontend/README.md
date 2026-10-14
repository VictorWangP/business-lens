# 前端开发

开发规则统一维护于 [AGENTS.md](AGENTS.md)。聊天交互优先使用 assistant-ui，通用 UI 优先使用 shadcn/ui。

## 菜单与页面

- 智能问数：对话工作区。
- 数据管理 → 业务数据：CSV / Excel 导入、数据预览、只读查询和业务指标口径，组件位于 `src/components/data/`。
- 数据管理 → 知识库：文档上传、解析、索引与知识库管理。
- 系统管理 → 应用配置：模型、开场白、常问问题、语音等应用设置。
- 反馈管理：保留现有待开发入口。

## 组件来源与维护

项目保持 React 18、Vite 和 Tailwind CSS 3。shadcn/ui 是引入到项目中维护的组件源码，不是一个统一的运行时组件包。

- 配置：`components.json`；组件目录：`src/components/ui/`；类名合并：`src/lib/utils.ts`。
- 使用官方 `new-york` 样式及 Radix primitives，颜色由 `src/index.css` 的明暗主题变量提供。
- 当前引入 26 个组件：Button、Input、Textarea、Label、Dialog、Select、Checkbox、Switch、Slider、Tooltip、DropdownMenu、AlertDialog、Progress、Table、Badge、Sidebar、Sheet、Separator、Collapsible、Alert、Sonner、Card、Avatar、Breadcrumb、ScrollArea、Skeleton。
- 参照 [shadcn/ui 的 Tailwind CSS 3 安装文档](https://v3.shadcn.com/docs/installation/vite)，添加组件时固定兼容的 CLI，避免自动迁移到其他 Tailwind 主版本：

```bash
cd frontend
npx shadcn@2.3.0 add <component>
```

先复用已有组件。组件更新时审查源码差异，并保留项目的中文文案、主题和可访问性设置。

## 本次迁移范围

| 区域 | 实现方式 |
| --- | --- |
| 模型配置 | shadcn Dialog、Select、Input、Checkbox、Slider、Badge、AlertDialog；保留发现模型、测试连接、批量添加、编辑及密钥复用逻辑 |
| 通用交互 | 登录、设置、知识库创建、引用详情使用 Dialog；会话操作使用 DropdownMenu；开关、输入、按钮、表格及进度条复用通用组件 |
| 导航与反馈 | 主菜单使用 Sidebar、Collapsible、Sheet；页头使用 Breadcrumb、Avatar；错误使用 Alert，操作反馈使用 Sonner；业务数据、指标和文档删除使用 AlertDialog |
| 聊天 | `useExternalStoreRuntime` 连接已有 SSE 状态，ThreadPrimitive、MessagePrimitive、ComposerPrimitive、ActionBarPrimitive 负责消息与输入交互 |
| 会话与消息操作 | ThreadListPrimitive 负责新建与切换；原生建议问题、复制、编辑、回到最新回答组件连接现有状态与接口 |
| 语音 | 原生 Dictate / StopDictation、Speak / StopSpeaking 通过 `src/lib/audio-adapters.ts` 连接现有录音转写和朗读服务；切换会话、页面或关闭语音配置时取消并释放资源 |
| Markdown | assistant-ui 的 MarkdownTextPrimitive 配合 remark-gfm 渲染标题、列表、表格与代码 |
| 业务内容 | Recharts 图表与指标通过 assistant-ui 工具消息渲染；查询证据、引用、执行阶段和知识库状态保留业务逻辑 |

会话列表支持业务空间切换，并仅显示所选空间的历史会话；置顶、重命名、删除和服务端持久化仍由外部运行时的 thread-list adapter 连接。

编辑消息后作为新问题发送，保留原有对话；再次发送也沿用这一语义。业务图表、查询证据和来源引用继续使用已有业务组件。业务查询结果以 Table 展示，保留原始数值精度、空结果与截断提示。

## 验证

```bash
npm run test
npm run build
```

测试覆盖模型发现与编辑、密钥复用、保存失败、手动填写 ID、Markdown/工具渲染、模型选择、停止后重发、原生会话操作、消息编辑和复制、移动端菜单、删除确认、查询表格及语音取消。会话切换时的迟到响应与转写结果也有隔离验证。组件测试使用 jsdom，外部模型服务和后端 SSE 用测试替身；真实服务连接与浏览器视觉效果需要运行应用验证。

聊天正文与延伸问题遵循 [统一回答协议](../docs/unified_answer_protocol.md)，建议问题直接从最终消息派生。
