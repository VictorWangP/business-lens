# LangGraph 重构验收记录

日期：2026-10-14。候选分支：`rag-langgraph`；独立目录：`/Users/vicwang/work/workspace/rag-langgraph`。

## 1. 结论与范围

非 Docling 重构已实现，自动化回归、真实 SQL 模型验收及新版启动检查通过。仍为独立候选版本，未合并 `main`，未完全切换旧环境。

按用户最新要求，**暂不继续验证 Docling**。保留 Docling/LangChain 文档适配，但真实文档检索及文档+SQL 联合验收尚未完成。嵌入模型曾返回 403（免费额度耗尽），不能将此次 SQL 通过解读为知识库链路通过。暂停前的 PDF/OCR 样例运行不作为完整知识库验收结论。

## 2. 已完成的替换

- LangChain `create_agent`、ToolStrategy、原生摘要与调用限制 middleware 替换旧 Agent 及固定消息裁剪。
- LangGraph SQLite checkpoint 承担模型历史、摘要、interrupt/resume 和节点恢复；完整展示归档与精确证据独立保存。
- 官方 LangGraph→AG-UI 适配器和 assistant-ui AG-UI runtime 承担标准事件、消息聚合及暂停界面，删除两套前端 SSE parser、通用事件聚合和 App 的第二份消息状态。
- 正文仅发布已校验的结构化答案投影。图表/表格从精确查询数据展示；内部工具结果、绘图结构、模型草稿及摘要不进入公开正文。显式要求代码时使用专用代码字段。
- 三个延伸问题与正文同一次结构化生成和持久化；关闭时为零。操作时间线保留并默认折叠，标题按数字编号。
- 新建独立 schema、密钥、依赖环境和 `storage-v2`，删除旧 schema/凭据迁移路径。活动后端、前端、测试和依赖没有 LlamaIndex 引用，新 Python 环境中相关包数量为零。

实现边界见 [新版实现说明](../langgraph_implementation.md)。授权、SQL policy、证据精度、任务调度和业务 UI 仍由应用负责，没有引入自定义通用 UI DSL 或第二套 Agent 循环。

## 3. 实际验证

| 检查 | 结果与范围 |
| --- | --- |
| 后端非 Docling 回归 | 148 passed、4 skipped、1 deselected；排除 `test_docling.py` 及命名含 docling 的联合样例 |
| 前端回归 | 14 个文件、48 项通过；使用实际 assistant-ui runtime/HttpAgent，服务端事件由测试提供 |
| TypeScript | `npx tsc --noEmit` 通过 |
| 生产构建 | Vite build 通过；仍有大于 500 kB 的 chunk 警告，未进行独立性能优化 |
| 完整依赖锁 | Python universal hashes 锁与 npm lock；按锁同步成功，`uv pip check` 兼容性检查通过 |
| 真实模型 SQL | 对合成订单实际查询，精确金额包含 0.30，折线图、表格、三个建议均返回；正文没有代码块或 xychart；25.06 秒完成 |
| 新版进程启动 | 独立端口 18001 上 health、ready、OpenAPI 均 HTTP 200；检查后停止进程 |
| 旧版回退检查 | 保留的旧环境启动/OpenAPI 正常；旧 LlamaIndex 执行器真实模型问答通过，期间一次格式修复；随后新版启动成功 |

真实 SQL 的可审查合成结果：[langgraph-real-sql-example.json](langgraph-real-sql-example.json)。该样例不含密钥或真实业务数据。测试使用临时数据库和文件目录，没有向旧业务库写入验收数据；真实模型仅收到合成问题/数据。临时解密的 provider 配置检查后已删除。

### 关键回归场景

- 建议开关、schema 纠正、编号标题、多个图表/表格及精确结果；模型中间代码/结构化草稿不进入公开事件。
- 认证、授权空间、模型配置、收藏、常问、反馈、语音接口及只读 SQL 规则。
- 原生摘要压缩 checkpoint，保留更正后的年度/月份/区域；模型 token 窗口与累计预算。
- 人工暂停后新建 executor 恢复；HTTP resume 输入校验、再次授权和重复请求去重。
- 官方 UI 暂停/继续和刷新续看；继续执行采用新的 assistant 消息段，解决旧消息 ID 碰撞导致答案不显示的问题。
- 已完成 checkpoint 恢复不再调用模型；待工具节点 checkpoint 恢复以 `input=None` 继续，不重复添加用户输入。
- worker lease 重新调度、显式取消、公开事件重放及结果发布边界。

最后一项节点恢复使用真实 SQLite checkpoint 构造持久化节点边界并重新创建 executor；不等同于生产进程在任意指令处强杀的故障注入验收。

## 4. 回退资产

- 旧源码基线：`6149727c05d0e4ef7c8c7e7f83d6352e5de0df5b`。
- 保护分支及标签：`baseline/pre-langgraph-20261014`；两者同名，脚本中应使用完整 ref 或 SHA。
- 原目录：`/Users/vicwang/work/workspace/rag-demo`；原 Python 环境、前端依赖、配置和数据保持独立。
- 私有备份：原目录 `.local-backups/legacy-20261014/`，包含 storage、配置、依赖清单与已验证的 `baseline.bundle`；不进入新版 Git。
- 没有配置远程仓库；这些是本地回退资产，不是异地备份。

回退时停止新版 API 和 worker，再在原目录用原依赖/配置启动。不要将新版数据库交给旧代码，也不要执行跨代 downgrade。完整说明见 [实施计划](../langgraph_docling_implementation_plan.md)。

## 5. 后续验收与已知限制

1. 按用户要求延后 Docling、真实文档检索、引用质量及联合问答验收；恢复验收前需要可用的嵌入模型额度。
2. PostgreSQL、Redis/Celery、Docker 实际部署未做现场验收；相关可选测试跳过不能视为通过。
3. 前端是运行时集成测试，未做真实浏览器视觉及网络故障全矩阵验收；新增媒体上传/生成业务也未扩展。
4. 摘要约束测试替换了 provider，未证明真实模型长会话摘要的全面忠实性。不能据此承诺所有早期条件永不丢失。
5. Python 有 datetime 与第三方适配器 API 弃用警告，构建有包体积警告；当前不阻断测试，但需随框架升级处理。
6. 未建立旧新版本严格同条件性能基准，不宣称速度、成本或总体行数降低比例。复杂度下降来自删除重复状态/协议实现、交由框架承担通用职责。

完整知识链路与部署验收完成并经用户审核后，再决定主线完全切换；当前保持可审核、可回退的独立候选版本。
