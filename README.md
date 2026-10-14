# 商析 · BusinessLens — rag-langgraph

企业数据分析与文档问答。Agent 使用 LangChain `create_agent`，执行状态和历史摘要使用 LangGraph checkpoint 与原生 SummarizationMiddleware；文档使用 Docling 官方 LangChain loader。前端使用 assistant-ui 官方 AG-UI runtime。

此目录为独立重构版本。旧版代码、数据库、配置和依赖环境保留在 `rag-demo`；新版直接建立新数据库，重新配置模型并导入资料。

## 本地启动

Python 3.12、Node.js 20+。从本项目根目录执行：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
backend/.venv/bin/python backend/scripts/prepare_local.py
npm ci --prefix frontend
```

初始化脚本生成独立密钥，初始化应用 SQLite 和 checkpoint SQLite。默认写入本目录 `storage-v2/`。已有 `.env` 不覆盖；密钥应私下保存，不提交 Git。

分别启动四个进程：

```bash
# 在 backend 目录：API
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
# 在 backend 目录：文档、索引与 Agent worker
.venv/bin/python -m app.workers.local
# 在 backend 目录：常问统计
.venv/bin/python -m app.workers.frequent
# 在 frontend 目录：前端
npm run dev
```

打开 [前端](http://localhost:5174) 或 [接口说明](http://localhost:8001/docs)，注册账号，在模型设置中配置对话和嵌入模型，然后导入 CSV/Excel、知识文档并配置业务空间。

默认使用 SQLite、DuckDB 和 Chroma，无需 Redis 或数据库服务。缺少模型、额度不足、证据为空和执行失败会明确报告。

## 主要能力

- CSV/Excel 查询快照、金额精度、授权视图与只读 SQL、业务指标。
- Docling 文档结构、页码、章节与表格；HybridChunker 切片；混合检索、相邻原文读取、版本发布与重建。
- 长会话原生摘要；聊天归档独立保存；精确查询结果使用稳定引用，不从摘要重建数值。
- 独立 worker 执行；浏览器断线不取消任务；标准事件重放；checkpoint 故障恢复；人工澄清暂停与继续。
- 编号标题、多个图表/表格、三个延伸问题、折叠执行过程；原始工具结果和内部模型草稿不进入公开正文。
- 认证、业务空间、收藏、常问、反馈管理与语音。

### 状态与通信

| 权威数据 | 保存位置 | 用途 |
| --- | --- | --- |
| 模型消息、摘要、暂停任务 | LangGraph checkpoint | Agent 继续执行 |
| 完整聊天正文与业务展示 | 应用消息归档 | 历史、复制、语音、反馈 |
| 精确查询及来源证据 | 授权 RunEvent 证据归档与知识索引 | 结果引用与溯源 |
| 有序公开事件 | RunEvent | AG-UI 断线重放 |

客户端不能注入工具、模型历史或图状态。服务端固定用户、会话、业务空间和范围版本；暂停恢复再次检查授权。具体边界见 [新版实现说明](docs/langgraph_implementation.md)。

## 依赖与配置

完整 Python 依赖锁定于 `backend/requirements.lock`，前端锁定于 `frontend/package-lock.json`。修改直接依赖后重新生成锁文件：

```bash
uv pip compile backend/requirements.txt --universal --generate-hashes --output-file backend/requirements.lock
```

Docling 首次处理 PDF/OCR 会下载解析模型。当前锁定 RapidOCR 3.9.1，避免 Docling 2.136 与 RapidOCR 3.10 的语言常量兼容问题。容器使用独立项目名和独立卷，不与旧版共享数据；`docker compose up --build` 暴露 API 8001。

模型预算在 `backend/.env.example` 中配置：上下文窗口、原生摘要触发/保留 token、输出上限、单次调用与总 token 预算。窗口应按实际模型能力设置。摘要会减少模型上下文，不删除聊天归档或精确结果。

## 验证

```bash
backend/.venv/bin/python -m pytest backend/tests -q
npm test --prefix frontend -- --run
npm run build --prefix frontend
```

PDF/OCR 验收需要首次下载模型，显式运行：

```bash
RAG_DOCLING_PDF_ACCEPTANCE=1 backend/.venv/bin/python -m pytest backend/tests/test_docling.py -q
```

真实模型测试使用显式提供的私有配置文件，未配置时跳过。不得把密钥加入测试代码、报告或 Git。当前实际结果和限制见 [验收记录](docs/validation/langgraph_refactor.md)。

## 回退与切换

旧版基线提交：`6149727c05d0e4ef7c8c7e7f83d6352e5de0df5b`。保护分支和标签均为 `baseline/pre-langgraph-20261014`；独立 bundle、数据、配置和依赖清单在原目录 `.local-backups/legacy-20261014/`。

回退时停止新版进程，进入保留的 `rag-demo`，使用原 `backend/venv`、原配置与原数据启动 API 8000、前端 5173。不要将新版数据库交给旧版，也不要执行跨代 downgrade。新版分支为 `rag-langgraph`，验收通过并审核后再切换主线。

- [批准的实施步骤](docs/langgraph_docling_implementation_plan.md)
- [当前实现与自定义职责](docs/langgraph_implementation.md)
- [实际验收与待处理事项](docs/validation/langgraph_refactor.md)

其他早期设计/评估文档保留为历史记录；新版启动与实现以以上文档为准。
