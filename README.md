# 经管之星 · BusinessLens

企业关系数据问答应用。系统采用一个 SQL Agent 查询经授权的 CSV、Excel、DuckDB、SQLite 和 PostgreSQL 数据源。Agent 使用 LangChain `create_agent`，LangGraph 保存可恢复执行状态；assistant-ui 官方 AG-UI runtime 管理前端会话消息。

## 本地启动

需要 Python 3.12、Node.js 20+。在项目根目录执行：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
backend/.venv/bin/python backend/scripts/prepare_local.py
npm ci --prefix frontend
```

初始化脚本生成本地配置并创建应用数据库和 checkpoint 数据库。默认使用 SQLite 与 DuckDB，不需要 Redis 或外部数据库服务。启动 API、后台任务和前端：

```bash
# backend 目录
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
.venv/bin/python -m app.workers.local

# frontend 目录
npm run dev
```

访问 [前端](http://localhost:5174) 或 [API 文档](http://localhost:8001/docs)，注册账号，配置支持工具调用的模型，导入表格或连接数据库，再创建业务空间。

统一 worker 默认运行 Agent 与常问任务。也可以使用 `--roles agent` 或 `--roles frequent` 分开部署；不要让多个进程同时消费常问任务。

## Linux 容器部署

完整步骤见[容器部署文档](docs/container-deployment.md)。生产配置包含前端 Nginx、API、统一 worker、数据库迁移与持久化数据卷：

```bash
bash scripts/deploy.sh init   # 生成独立部署密钥，仅执行一次
# 按部署文档编辑 deploy/.env
bash scripts/deploy.sh build
bash scripts/deploy.sh up
```

默认仅监听服务器 `127.0.0.1:8080`，通过 HTTPS 网关或 SSH 隧道访问。升级前自动备份已有实例；备份、恢复和本地数据迁移限制见部署文档。

## 主要行为

- SQL 只读执行，并按用户与业务空间授权数据源、视图和列。
- LangGraph checkpoint 保存模型历史及暂停任务；应用归档保存聊天展示和可重放运行事件。
- 查询结果按会话与范围保存为精确证据；历史摘要不会替代查询证据。
- 最终答案、表格、指标、图表、延伸问题和操作过程使用统一的业务展示契约。
- 反馈、常问、收藏、模型配置和语音属于应用功能；业务事实来自授权数据查询。

数据导入和授权边界见[业务数据导入技术设计](docs/业务数据导入技术设计.md)与[业务空间和会话绑定技术设计](docs/业务空间和会话绑定技术设计.md)。上下文摘要和工具结果整理策略见[会话上下文管理](docs/agent_context_management.md)。

## 验证

```bash
backend/.venv/bin/python -m pytest backend/tests -q
npm test --prefix frontend -- --run
npm run build --prefix frontend
```

真实模型测试只有在本地提供私有配置时才会运行。数据库 schema 由 Alembic 管理。已有本项目数据库升级时，在 `backend` 目录执行 `.venv/bin/python -m alembic upgrade head`；不支持旧版知识库数据库的跨代迁移。

`0002_cleanup_legacy` 删除已停用的 `memory_facts` 和内置演示 `sales_orders` 表，并移除运行范围中的空 `kb_ids`。非空旧表数据与修改前的范围快照先导出至 `STORAGE_DIR/.local-backups/cleanup-legacy/`，导出文件权限为 `0600`；遇到非空知识库范围时迁移停止。执行前应使用 SQLite backup API 保存完整应用库，回退时停止应用后恢复该备份。checkpoint 数据库继续用于 Agent 恢复，不在此迁移中修改。

## 配置

Python 依赖锁定于 `backend/requirements.lock`，前端依赖锁定于 `frontend/package-lock.json`。示例配置见 `backend/.env.example`。模型上下文容量、摘要阈值、输出上限和执行限制都可按部署配置。百炼及 MaaS endpoint 会关闭 thinking 模式，以兼容当前结构化工具调用。
