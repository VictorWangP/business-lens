# 商析 · BusinessLens

**AI 业务数据检索与分析平台** · 项目标识：`business-lens`

本地文件驱动的业务分析与 Agent RAG：CSV / Excel 保存为可查询的数据快照，文档经 Docling 解析后进入知识索引，LlamaIndex FunctionAgent 按问题多次调用检索、原文阅读和只读 SQL 工具，最终回答附带可检查的证据。

默认无需 PostgreSQL、Redis 或 Docker。应用记录使用 SQLite，业务文件使用 DuckDB，向量使用 Chroma。生产路径不会返回模拟销售数字或预设成功答案；缺少模型配置、工具失败和超时会明确报告。

## 本地启动

推荐 Python 3.12、Node.js 20+ 和 npm。以下命令适用于 macOS / Linux；除明确写出 `cd` 的命令块外，均在项目根目录执行。默认本地开发需要四个常驻进程：API、文档与 Agent worker、常问 worker、前端。

首次安装：

```bash
python3.12 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt
backend/venv/bin/python backend/scripts/prepare_local.py
```

`prepare_local.py` 首次生成 `backend/.env` 的独立密钥，在修改已有 SQLite 数据库前创建备份，执行 Alembic 迁移，并将旧模型配置中的明文 API Key 加密。已有 `.env` 不会被覆盖；需根据 `backend/.env.example` 补齐 `CREDENTIAL_KEY` 和 `SECRET_KEY`。`SECRET_KEY` 至少 32 字节，`CREDENTIAL_KEY` 必须是有效的 Fernet 密钥。请保存密钥，丢失加密密钥将无法读取已保存的凭据。

分别在四个终端启动：

```bash
# 终端 1：后端
cd backend
venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# 终端 2：文档处理进程（数据库持久队列）
cd backend
venv/bin/python -m app.workers.local
```

```bash
# 终端 3：常问统计进程（单实例，独立于文档处理）
cd backend
venv/bin/python -m app.workers.frequent
```

```bash
# 终端 4：前端（/api 自动代理到后端）
cd frontend
npm ci
npm run dev
```

打开 [前端](http://localhost:5173)，注册账号并登录。接口说明见 [Swagger UI](http://localhost:8000/docs)。Vite 将 `/api` 代理到 `http://localhost:8000`，代理目标配置在 `frontend/vite.config.ts`。若修改后端端口，应同步修改该配置。

API 启动后可在项目根目录检查：

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8000/api/ready
```

`health` 返回服务存活状态；`ready` 检查应用数据库，启用 Celery 时也检查 Redis。它们不验证模型服务，也不表示后台 worker 正在运行。文档或 Agent 任务一直处于排队状态时，先检查 worker 终端。

在对应终端按 `Ctrl+C` 停止进程。本地开发使用 `--reload` 自动加载后端代码修改；未启用时，修改代码后需重启后端。修改 `.env` 后应重启 API 和 worker。

### 升级已有安装

先停止 API 和 worker，再在项目根目录执行：

```bash
backend/venv/bin/python -m pip install -r backend/requirements.txt
backend/venv/bin/python backend/scripts/prepare_local.py
npm --prefix frontend ci
```

随后按上面的三个终端命令重新启动。`prepare_local.py` 仅支持 SQLite，备份位于数据库同目录，文件名形如 `app.db.backup-时间戳`。该备份仅包含应用数据库；完整备份还需保留 `storage/` 中的业务快照、原文件和索引，以及 `backend/.env` 中的密钥。

### Docker Compose 启动后端

安装 Docker 和 Compose 插件后，可用容器运行迁移、API 和 worker。首次使用先生成配置；已有 `backend/.env` 时跳过初始化命令：

```bash
backend/venv/bin/python backend/scripts/init_env.py
```

此初始化命令需要已安装 `backend/requirements.txt` 中的依赖。确认 `backend/.env` 已包含有效密钥后，在项目根目录执行：

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f api worker
```

`migrate` 成功退出后，API 和 worker 才会启动。API 暴露在 `127.0.0.1:8000`，前端仍需在宿主机执行 `npm --prefix frontend ci` 和 `npm --prefix frontend run dev`。后端数据保存到名为 `artifacts` 的 Compose 卷，并挂载到容器 `/data`；它与宿主机默认 `storage/` 是两份独立数据，已有本地记录不会自动导入。

```bash
# 修改后端代码或依赖后重新构建并启动
# 升级前先备份卷中的数据及 backend/.env
docker compose up -d --build
# 停止并移除容器，保留数据卷
docker compose down
```

容器访问宿主机上的模型服务时，Base URL 应使用 `http://host.docker.internal:端口/v1`；`localhost` 指向容器自身。Compose 当前仅覆盖默认 SQLite + 数据库任务队列，不包含前端、PostgreSQL 或 Redis 服务。

## 配置与数据目录

后端从 `backend/.env` 读取配置，进程环境变量可覆盖同名项。配置定义见 `backend/app/config.py`，示例见 `backend/.env.example`。对话和嵌入模型在登录后的“系统管理 → 应用配置 → 模型设置”保存，不通过 `.env` 配置。

| 配置项 | 默认值 / 用途 |
| --- | --- |
| `SECRET_KEY` / `CREDENTIAL_KEY` | 登录令牌签名 / 模型及数据源凭据加密；初始化脚本生成独立密钥 |
| `DATABASE_URL` | `sqlite+aiosqlite:////绝对路径/business-lens/storage/app.db`；应用记录和持久任务 |
| `STORAGE_DIR` | 项目根目录下的 `storage/`；用户文件、DuckDB 快照、解析产物及 Chroma 索引 |
| `TASK_BACKEND` | `database`；由 `python -m app.workers.local` 轮询任务 |
| `CORS_ORIGINS` | `["http://localhost:5173"]`，使用 JSON 数组格式 |
| `AGENT_MAX_STEPS` / `AGENT_MAX_TOOL_CALLS` | `12` / `16`；单次 Agent 的步数 / 工具调用数限制 |
| `AGENT_TIMEOUT` / `AGENT_MAX_TOTAL_TOKENS` | `180` 秒 / `64000`；运行时间 / 总 token 预算 |
| `AGENT_WORKER_CONCURRENCY` | `5`；Agent 后台 Worker 的并发运行数上限，超出后在数据库队列等待 |
| `SQL_TIMEOUT_MS` / `SQL_MAX_ROWS` | `15000` 毫秒 / `200` 行；SQL 超时 / 最大返回行数，超出显示截断 |
| `MAX_UPLOAD_BYTES` | `52428800`（50 MiB）；业务文件和知识库文档上传限制 |
| `RETRIEVAL_MIN_SIMILARITY` | `0.25`；向量召回余弦相似度阈值 |
| `RERANK_API_URL` / `RERANK_MODEL` / `RERANK_API_KEY` | 可选外部重排服务 |
| `STT_API_BASE` / `STT_API_KEY` / `STT_MODEL` | 百炼语音识别配置，默认模型 `qwen3-asr-flash`；密钥可复用当前用户模型配置中的默认百炼模型凭据 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 可选 OpenTelemetry collector 地址 |

`DATABASE_URL` 和 `STORAGE_DIR` 是独立配置：更换存储目录时需同时检查数据库路径，API 与 worker 必须使用相同配置及可访问的存储。默认 `storage/app.db` 保存账号、配置、会话、任务和切片；`storage/chroma/` 保存向量索引，`storage/users/` 保存用户文件和数据快照。语音输入使用百炼 ASR；回答朗读使用浏览器本机可用的中文音色，音色依赖客户端设备。

可选 S3 存储通过 `STORAGE_BACKEND=s3`、`S3_BUCKET`、`S3_ENDPOINT`、`S3_REGION` 及 AWS 凭据或部署角色配置。它不将 SQLite、DuckDB 或 Chroma 变成共享数据库。

## 使用真实数据

1. 注册或登录，在“数据管理 → 业务数据”上传 CSV / Excel。首行为唯一列名；CSV 使用 UTF-8，Excel 支持 `.xlsx`，公式需先粘贴为值。默认导入第一张工作表，也可指定工作表名称；多个工作表分别导入。
2. 点击“查看数据”，检查推断的字段类型，并运行只读 SQL 验证结果。每个文件提供 `main.dataset` 视图，字段含中文或空格时使用双引号。单文件默认最多 50 MiB、10 万行、200 列；导入生成独立快照，重新导入会创建新的数据集。
3. 在“模型设置”添加支持工具调用的真实对话模型，填写 Base URL、API Key 和模型 ID，并选择默认对话模型后保存。模型配置仅从当前用户保存的设置读取，不使用环境变量回退；服务地址必须提供 OpenAI 兼容接口。
4. 使用文档 RAG 时，在“模型设置”单独添加真实嵌入模型，填写 Base URL、API Key 和模型 ID，并选择默认嵌入模型后保存。在知识库上传政策、手册等文件，等待 worker 处理至“就绪”。旧文档需要点击“重建索引”；更换嵌入模型时使用“全库重建”，全部文档成功后一次切换。迁移完成前保留旧模型配置，检索会使用旧索引对应的模型；缺少旧模型或向量服务失败时明确降级到关键词检索。
5. 在聊天中勾选业务数据集和知识库，再提问。例如：“汇总 2026 年 1 月各区域销售额，检索相关折扣政策，解释异常并列出依据。”实际结论取决于上传的数据与证据。
6. 展开回答中的查询记录和文档引用，检查 SQL、参数、真实行集、执行时间、文档页码和章节；执行记录可通过 `/api/runs/{run_id}` 查看。

知识库允许上传 `.pdf`、`.docx`、`.pptx`、`.xlsx`、`.html`、`.md`、`.txt` 和 `.csv`，单文件默认最多 50 MiB。业务数据上传用于结构化 SQL 查询，知识库上传用于文档切片检索；CSV / Excel 应按用途选择入口。

不使用知识库时，业务文件 SQL 分析只需要对话模型。文档检索需要独立的嵌入服务。PDF/OCR 的 Docling 首次处理可能下载模型；离线部署需预先准备模型缓存。TXT 使用明确的 UTF-8 文本解析路径，其余支持格式进入 Docling，不会在解析失败后悄悄降级。

模型配置支持编辑已有模型。新增时填写供应商 Base URL 和 API Key 后，会自动调用 OpenAI 兼容的 `/models` 接口，返回模型可从下拉框选择，也可批量添加全部返回模型。批量添加按当前选择的 LLM / Embedding 类型配置；供应商包含混合类型时应分别添加或编辑模型类型。选择“已配置供应商”可复用已有凭据，无需重复输入密钥。子弹窗确认后，需在模型配置主弹窗点击“保存”提交。

“测试连接”验证供应商连接、认证和模型列表接口，显示认证失败、限流、超时等原因；不代表每个模型均可推理或支持工具调用。不支持 `/models` 的供应商可手动填写模型 ID。编辑模型时 `********` 表示保留已有密钥，修改 Base URL 后需重新输入密钥。

聊天提交后会持续显示当前工作阶段和等待时间，包括准备回答、检索或查询数据、分析结果和生成回答；任务完成、失败或停止时结束提示。

Agent 任务由后台 Worker 独立执行。切换会话或 SSE 断开不会停止任务；切回会话会恢复已保存的状态和事件。停止按钮只取消当前 Agent 运行。不同会话可并行执行，数量受 `AGENT_WORKER_CONCURRENCY` 限制；同一会话在有活动任务时不能继续提交。升级到此版本后运行 `backend/scripts/prepare_local.py`（或部署迁移服务）应用 `0007_agent_background_runs` 数据库迁移。

业务指标可在“指标口径”中定义日期参数 SQL，Agent 优先使用这些定义：

```sql
SELECT SUM("金额") AS total
FROM dataset
WHERE "日期" >= :start_date AND "日期" < :end_date
```

金额按可表示的十进制值保存，查询结果中的 Decimal 以字符串传输，避免 JSON 浮点转换改变金额。超出十进制精度或混合类型的列保留为文本，字段类型可在导入后检查。图表从查询结果生成，截断结果不会生成全量汇总卡片，也不会编造同比或环比。

## 可选基础设施

默认本地启动不需要以下依赖。按需在项目根目录安装：

```bash
# PostgreSQL 业务连接 / PostgreSQL 应用数据库 / pgvector
backend/venv/bin/python -m pip install -r backend/requirements-postgres.txt
# Celery + Redis 任务队列
backend/venv/bin/python -m pip install -r backend/requirements-celery.txt
```

PostgreSQL 业务连接通过 `/api/data-sources` 创建，提供连接 URL、业务 schema 和授权视图列表，使用独立只读账号；当前前端的业务数据入口以文件导入为主。连接现有业务数据库不要求将 SQLite 应用数据库迁移到 PostgreSQL。接口格式可在 Swagger UI 查看。

若将应用数据库切换为 PostgreSQL，需先准备支持 pgvector 的数据库，设置 `DATABASE_URL=postgresql+asyncpg://账号:密码@主机:5432/数据库名`，以迁移账号在 `backend` 目录执行 `venv/bin/python -m alembic upgrade head`，不能使用 `prepare_local.py`。`scripts/provision_runtime.py` 可在迁移后按 `APP_DATABASE_USER` / `APP_DATABASE_PASSWORD` 配置非所有者运行账号，随后需将 API 和 worker 的 `DATABASE_URL` 切换为该账号。旧 SQLite 应用记录迁移工具为 `scripts/migrate_legacy.py --sqlite /绝对路径/app.db`，默认只查看数量，`--apply` 才写入已迁移且应用表为空的 PostgreSQL；它不是当前数据库的全量备份恢复工具。

启用 Celery 时，先准备 Redis，在 `.env` 设置 `TASK_BACKEND=celery` 和 `REDIS_URL`，重启 API，再用以下进程替代本地 worker。Beat 用于恢复任务及派发维护任务：

```bash
cd backend
venv/bin/python -m celery -A app.workers.tasks:celery worker --loglevel=INFO
```

```bash
# 另一个终端
cd backend
venv/bin/python -m celery -A app.workers.tasks:celery beat --loglevel=INFO
```

启用这些适配层仍需规划文件快照和索引的访问方式，不能直接视为多机部署完成。

## 架构与扩展

Text2SQL 调用链、关系数据库 Agent 查询设计及分阶段扩展方案见 [Text2SQL 设计文档](docs/text2sql_agent_design.md)。

| 模块 | 职责 | 当前技术 |
| --- | --- | --- |
| 前端 | 文件导入、数据预览、资源选择、执行事件与证据展示 | React / TypeScript / Vite / assistant-ui / shadcn/ui / Recharts / SSE |
| API 与应用层 | 身份鉴权、用户隔离、会话、指标定义、运行记录 | FastAPI / Pydantic / SQLAlchemy / SQLite |
| Agent | 选择工具、补充检索、读取上下文、查询业务、合成答案 | LlamaIndex FunctionAgent / OpenAI 兼容模型 |
| 文档处理 | 持久任务、重试、结构保留、切片、版本激活 | Docling / HybridChunker / LlamaIndex TextNode |
| 检索 | 显式嵌入、向量与关键词召回、排名融合、可选重排 | Chroma / SQLite FTS5 / jieba / RRF |
| 业务查询 | 类型推断、不可变文件快照、受限只读 SQL | CSV / openpyxl / Arrow / DuckDB / SQLGlot |
| 存储与观测 | 原始文件、解析产物、模型凭据、执行审计 | 本地文件或可选 S3 / Fernet / OpenTelemetry |

具体边界、数据流、失败处理及扩展约束见 [架构说明](docs/architecture.md)。向量计算、Chroma / pgvector 存储、中文混合检索、模型迁移及维护约束见 [向量服务设计与实现方案](docs/vector_service_design.md)。前端组件来源与维护方式见 [前端开发说明](frontend/README.md)，开发规则见 [frontend/AGENTS.md](frontend/AGENTS.md)。当前默认部署是单机架构；数据源、模型、存储和任务调度均有独立适配层，扩容时可替换基础设施并迁移索引，不能直接把本地目录用于多机共享。

## 验证

知识库支持编辑和删除、原件下载、分页切片预览、检索调试及处理/维护任务查看。“修复索引”从已保存的 SQL 向量补回缺失的 Chroma 条目、清理失效向量并重建 FTS5，不调用嵌入服务；源切片丢失时需重建。删除和重建产生的文件/向量清理由 worker 持久处理，失败自动重试，达到五次后可在维护任务中重新提交。历史聊天证据快照仍保留。

真实模型验收在临时数据库和存储中运行，不写入现有知识库；仅向当前配置的模型服务发送验收文件。存在多个可用用户配置时需传 `--user-id`。`--agent` 同时验证真实对话模型的检索与引用。

```bash
backend/venv/bin/python backend/scripts/validate_knowledge.py --smoke --agent --output /tmp/knowledge-smoke.json
# 可选：增加一份实际文件及其验收问题
backend/venv/bin/python backend/scripts/validate_knowledge.py --smoke --document /path/to/policy.pdf --query '该政策的审批要求是什么？'
# 使用自有知识库和标注问题集评估文档级 Recall@K、MRR、无答案检索准确率
backend/venv/bin/python backend/scripts/validate_knowledge.py --user-id USER_ID --kb-id KB_ID --cases docs/knowledge_eval.example.json --output /tmp/knowledge-eval.json
```

评测前将示例中的文档 ID 和问题替换成实际标注，建议分别运行 `--mode hybrid`、`--mode vector`、`--mode keyword` 比较。`RETRIEVAL_MIN_SIMILARITY` 默认 0.25，仅筛选向量召回；关键词命中和模型回答仍需业务验收，阈值应按真实数据调整。评测工具的无答案准确率只检查是否返回切片，不等于生成答案准确率。

```bash
backend/venv/bin/python -m pytest backend/tests -q
npm --prefix frontend run test
npm --prefix frontend run build
# 前端交互式监听测试
npm --prefix frontend run test:watch
```

测试覆盖真实 CSV/XLSX → DuckDB 查询、金额精度、日期参数、SQL 限制、用户隔离、实际 Docling Markdown 解析、Chroma/FTS5 检索、失败重建保留旧版本、迁移及 LlamaIndex 多轮工具调用。LLM 和嵌入服务在自动化测试中使用测试替身，测试结果不能代表外部模型服务已通过现场验收。

后端测试默认使用临时 SQLite 和存储目录。PostgreSQL 集成测试默认跳过；如需运行，先安装 PostgreSQL 可选依赖，再设置 `RAG_TEST_POSTGRES_URL` 指向独立测试库的管理员连接 URL。测试会创建并清理临时 schema 和角色，pgvector 测试还会执行 `CREATE EXTENSION IF NOT EXISTS vector`。

前端构建产物在 `frontend/dist/`。`npm --prefix frontend run preview` 仅用于本地预览构建产物；预览服务器沿用开发服务器的 `/api` 代理，仍需运行后端。正式部署需为同源 `/api` 配置反向代理到后端，并支持 SSE 流式响应。

## CSV 演示数据包

已生成 20 份模拟 CSV，共 162,366 行，覆盖销售、目标、应收、CRM、营销、项目风险和库存。文件、字段口径及 32 个演示提问与标准 SQL 见 [数据包指南](datasets/demo_csv/README.md)。先导入月度销售、大区收入和跨年对比三个小文件即可演示折线图、柱状图和饼图，再使用 8 万行销售明细进行复杂聚合。

在项目根目录运行数据包校验：

```bash
backend/venv/bin/python backend/scripts/validate_demo_csv.py
```

该命令在临时存储中导入全部 CSV 并执行标准 SQL，校验金额、数量和图表结果，更新 `datasets/demo_csv/validation_report.json`，不调用外部模型。

如需重新生成演示数据包：

```bash
# 仅在需要创建或重置模拟参考库时执行：会删除并重建 storage/business_data.db
backend/venv/bin/python backend/scripts/init_business_dataset.py
# 只读参考库，覆盖数据包目录中的同名生成文件
backend/venv/bin/python backend/scripts/generate_demo_csv.py
backend/venv/bin/python backend/scripts/validate_demo_csv.py
```

`generate_demo_csv.py` 依赖 `storage/business_data.db` 中的参考表和视图，也支持 `--output /目标目录`。上述生成命令不会自动创建当前用户的数据源；生成后仍需在页面导入 CSV。已有数据包可直接使用，无需初始化参考库。

## 自动常问问题

聊天保存用户消息时，在同一事务中创建待处理记录。独立常问 worker 顺序处理：保守空白归一化、精确匹配、Embedding Top 3 召回和一次 LLM 资格/同义判定。每个用户、知识库集合和数据源集合独立累计，默认达到 3 次展示，最多 10 条。点击只填入输入框，提交后按当前资源重新查询。

应用配置中设置开关和正整数阈值。关闭时跳过未完成任务，关闭期间不补算；删除会话后实时聚合剩余次数。嵌入模型变化会暂停当前用户的统计，进入常问设置重置后从新提问累计。常问统计初始为空，手工推荐在开场白中配置。

`GET /api/frequent-questions` 使用重复查询参数 `kb_ids`、`source_ids`，返回 `id/question/count/last_asked_at`；`DELETE /api/frequent-questions` 只清除当前用户的常问记录及分组，保留聊天和业务数据。需登录。Docker Compose 包含独立 `frequent-worker`，共享存储锁保证单机单实例。

验证及真实模型验收方法见 [常问验证记录](docs/validation/frequent_questions.md)。


### 会话业务范围

在独立“业务空间”页面创建或编辑空间，并关联业务数据源与知识库。会话列表顶部选择当前业务空间，历史列表仅展示该空间的会话；输入框下方不展示空间信息，聊天区不提供来源配置。

切换业务空间会加载该空间最近更新的会话；没有历史时显示绑定该空间的空白草稿。新建对话自动绑定会话列表中当前选择的空间；已有会话固定绑定空间，切换空间后查看其会话历史。空间配置更新对所有关联会话的后续提问生效，进行中的执行和历史回答保持原样。每次执行保存配置版本与来源快照，变更前的问答不进入新范围的模型上下文。

配置缺失或来源失效时，保留原问题；在消息区提示中进入业务空间管理页修复，返回对话后可点击“继续提问”。未发送草稿以及空间编辑中的选择在管理页往返时保留。

已有数据库需在 `backend` 目录执行 `venv/bin/python -m alembic upgrade head`。`0006_workspace_binding` 为会话绑定空间并保留历史来源范围；`0007_agent_background_runs` 增加 Agent 后台任务执行所需的输入快照、消息关联和 Worker lease。上一版会话临时来源与空间配置不一致时，迁移会创建“历史范围”兼容空间，保留会话原范围及消息，不静默合并来源。详细设计及实施记录见 [会话范围设计](docs/conversation_resource_scope_design.md)。


## 反馈管理与回复校对

助手回答完成后可点击“反馈错误”，提交原因和补充说明。处理人员在“反馈管理 → 回复校对”中搜索、筛选并登记核查结果；标记已处理必须填写备注，支持重新打开并保留历史。处理不会改写原回答或自动修复源数据。

升级现有数据库需先备份，再在 `backend` 目录执行 `venv/bin/python -m alembic upgrade head`，应用 `0008_answer_feedback`。SQLite 本地环境可使用现有的 `backend/venv/bin/python backend/scripts/prepare_local.py` 备份并升级。新用户和已有用户默认均无反馈管理权限，通过用户 UUID 显式配置：

```bash
backend/venv/bin/python backend/scripts/set_feedback_admin.py --user-id USER_UUID
# 撤销反馈管理权限
backend/venv/bin/python backend/scripts/set_feedback_admin.py --user-id USER_UUID --revoke
```

角色更新后刷新页面或重新登录生效；服务端每次请求检查数据库角色。反馈管理员可查看当前部署内所有上报的问答证据，适用于单组织部署；原会话、运行和文档接口继续按用户所有权隔离。删除会话保留已提交的反馈快照。处理备注仅供处理人员查看，提交者在原消息处查看状态。

详细规则见 [反馈管理设计](docs/feedback_management_design.md)，实施和验收记录见 [反馈管理验收](docs/validation/feedback.md)。
