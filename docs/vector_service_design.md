# 向量服务设计与实现方案

本文依据 2026-10-12 的仓库实现整理，供向量相关功能开发、排障和部署查阅。这里的“向量服务”是应用内的嵌入、索引、检索与维护模块集合，当前没有独立的向量服务 HTTP 进程。代码发生变化时，应同步更新本文；具体模型、凭据和临时运行状态不作为设计常量记录。

## 1. 方案与职责边界

默认部署采用“独立 Embedding API + 本地 Chroma + SQLite 全文与关键词索引 + 混合检索”。Chroma 只接收显式向量，不计算文本向量，也不自动选择或下载嵌入模型。

| 环节 | 默认本地实现 | 可选 PostgreSQL 路径 |
| --- | --- | --- |
| 文档解析与分块 | TXT 文本解析；其余支持格式使用 Docling / HybridChunker | 相同 |
| 向量计算 | 用户配置的 OpenAI 兼容 Embedding API | 相同 |
| 向量持久化 | Chroma；SQLite 同时保存向量副本 | PostgreSQL 的 pgvector 列 |
| 向量检索 | Chroma HNSW，余弦距离 | pgvector 余弦距离排序 |
| 文本、来源、版本 | SQLite `document_chunks` / `documents` | 对应 PostgreSQL 表 |
| 中文关键词检索 | jieba + FTS5 / BM25 | jieba + `simple` 全文配置 / `ts_rank` |
| 排名融合 | RRF | 相同 |
| 可选重排 | 独立 HTTP rerank 接口 | 相同 |

当前默认是单机架构：API 和 worker 访问同一 SQL 数据库与存储目录。Chroma 使用嵌入式 `PersistentClient`，无需另起 Chroma 服务。业务 CSV / Excel 的 DuckDB 查询链路独立于向量检索，不要求先向量化。

PostgreSQL 是可选分支，需要 `requirements-postgres.txt`、vector 扩展和独立验收。当前迁移没有创建 pgvector HNSW / IVFFlat 索引，不能将这条路径描述为已具备近似最近邻索引优化。仅修改数据库 URL 也不会自动迁移已有文档和索引。

## 2. 代码导航

以下路径均相对于仓库根目录。

| 文件 | 职责与主要入口 |
| --- | --- |
| [embeddings.py](../backend/app/infrastructure/embeddings.py) | `EmbeddingProvider`：模型指纹、历史模型解析、批量向量计算与返回校验 |
| [llm_service.py](../backend/app/services/llm_service.py) | `get_model_config(..., kind='embedding')`：读取当前用户模型配置 |
| [vector_index.py](../backend/app/infrastructure/vector_index.py) | `VectorIndex`：Chroma 集合、写入、查询、删除、核对与清理 |
| [vector_types.py](../backend/app/infrastructure/vector_types.py) | pgvector / SQLite JSON 向量列类型适配 |
| [lexical_index.py](../backend/app/infrastructure/lexical_index.py) | SQLite FTS5 外部内容表及事务内同步触发器 |
| [parser.py](../backend/app/ingestion/parser.py) | 解析、分块和来源元数据 |
| [pipeline.py](../backend/app/ingestion/pipeline.py) | 入库、任务领取、失败处理、版本激活与批量迁移 |
| [maintenance.py](../backend/app/ingestion/maintenance.py) | 索引修复、持久清理任务及重试 |
| [retriever.py](../backend/app/retrieval/retriever.py) | `KnowledgeRetriever`：关键词 / 向量召回、融合、诊断；`read_chunk`：相邻原文 |
| [reranker.py](../backend/app/retrieval/reranker.py) | 可选重排接口适配 |
| [platform.py](../backend/app/models/platform.py) | `DocumentChunk`、`IngestionJob`、`MaintenanceJob` 等持久模型 |
| [knowledge.py（API）](../backend/app/api/knowledge.py) | 上传、重建、切片、搜索、修复与维护接口 |
| [knowledge.py（Schema）](../backend/app/schemas/knowledge.py) | `RetrievalProbe` 等请求响应结构 |
| [executor.py](../backend/app/agents/executor.py) | Agent 的 `search_knowledge` / `read_document_section` 工具 |
| [local.py](../backend/app/workers/local.py) | 默认数据库队列 worker |
| [config.py](../backend/app/config.py) | 存储、数据库、检索阈值、重排等环境配置 |

## 3. 模型与环境配置

### 3.1 嵌入模型配置来源

嵌入模型从当前用户 `AppConfig(config_key='model_setting')` 中读取：

- `default_embedding_model` 指定默认嵌入模型 ID。
- `available_models` 中对应条目必须显式设置 `type='embedding'`，并配置 `id`、`base_url`、加密保存的 `api_key`。
- `get_model_config` 校验功能启用状态、模型是否存在、类型、HTTP(S) 地址和有效 Key；返回运行时解密配置。
- 当前实现不再从环境变量回退选择 LLM / Embedding 模型。旧的 `EMBEDDING_MODEL`、`EMBEDDING_API_BASE`、`EMBEDDING_API_KEY` 即使留在 `.env`，也不会由这条链路读取。

使用 `AsyncOpenAI` 表示遵循 OpenAI 兼容接口协议，不代表只能使用 OpenAI 服务。可以接入第三方服务，也可以接入本地兼容服务；当前配置校验仍要求非空有效 Key。本地服务也需提供可通过校验的 Key 值。

文档切片和问题文本会发送到所配置的嵌入端点；启用重排时，问题及候选文本也会发送到重排端点。模型列表或“测试连接”成功不能代替真实 embeddings 请求验收。不要在本文、日志或诊断返回中记录明文凭据。

### 3.2 环境配置

| 配置 | 默认值 / 作用 |
| --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///.../storage/app.db`；决定本地 / PostgreSQL 路径 |
| `STORAGE_DIR` | 仓库根目录下 `storage` |
| `CHROMA_PERSIST_DIR` | 只读派生属性：`STORAGE_DIR / 'chroma'`，不是独立环境配置项 |
| `CREDENTIAL_KEY` | 解密用户模型凭据及任务配置快照，需妥善保存 |
| `TASK_BACKEND` | `database`；可选 `celery`，需要额外依赖和部署 |
| `RETRIEVAL_MIN_SIMILARITY` | `0.25`，仅筛选向量候选，范围 `[-1, 1]` |
| `RERANK_API_URL` | 空值表示不启用重排 |
| `RERANK_MODEL` / `RERANK_API_KEY` | 重排端点的模型及凭据 |

API 与 worker 必须使用一致的配置和 `CREDENTIAL_KEY`。环境配置由 `backend/.env` 加载，进程环境可覆盖对应设置。修改后需重启相关进程。

## 4. 向量计算与数据契约

### 4.1 EmbeddingProvider

`embed(texts)` 以每批 32 条顺序调用 `client.embeddings.create(model=model_id, input=batch)`，客户端超时为 90 秒，`max_retries=2`。按返回的 `index` 排序后，校验数量及索引顺序，再校验向量非空、维度一致、数值有限且不是全零向量。无效返回会抛错，不使用随机向量或模拟成功结果。

当前没有显式传递 `dimensions`、查询指令或文档 / 查询任务类型参数，也没有应用侧向量归一化、缓存和跨批并发。需要这些能力时应扩展 Provider 契约，并评估是否改变向量空间；不要在 Chroma 适配器中隐式补入模型逻辑。

### 4.2 模型指纹与集合

当前指纹算法为：

```python
identity = json.dumps([base_url, model_id], ensure_ascii=False)
profile = hashlib.sha256(identity.encode()).hexdigest()
collection_name = f'p_{profile[:40]}_d{dimension}'
```

通过 `get_model_config` 读取的 URL 已去掉尾部 `/`。指纹不包含 API Key，轮换密钥不会改变索引身份；不包含模型实际权重版本、提示指令或输出参数。若服务商在同一地址和模型 ID 下更新权重，当前实现无法自动识别。同维度也不代表向量空间兼容；这类变更需要重建，未来增加版本 / 参数时也应调整指纹与兼容策略。

Chroma 集合设置 `embedding_function=None`、`hnsw:space='cosine'`，客户端关闭匿名遥测。写入每批最多 500 条。集合按模型指纹和维度划分，集合内多个用户 / 知识库依靠过滤条件隔离。

### 4.3 存储契约

| 对象 | 保存内容 |
| --- | --- |
| Chroma | 切片 ID、显式向量，及 `user_id`、`kb_id`、`version`、`doc_id` 元数据；不写入正文 |
| `DocumentChunk` | 切片 ID、归属、版本、序号、正文 `content`、来源 `meta`、`embedding_profile`、向量 `embedding`、分词文本 `keywords` |
| `Document.active_version` | 当前可用于检索的版本 |
| `IngestionJob` | 文档任务、内容哈希、目标版本、批次、尝试次数、状态、加密模型配置快照 |
| `MaintenanceJob` | 独立于文档生命周期的修复 / 清理任务、状态与结果 |
| 文件存储 | 原件和 `{user_id}/artifacts/{doc_id}/{version}/document.json`、`document.md` 解析产物 |

SQLite 中 `embedding` 是 JSON；PostgreSQL 路径使用 pgvector。SQL 有效切片是正文和有效版本的权威来源，Chroma 是可从 SQL 向量副本修复的检索索引。不能仅凭 Chroma 中存在记录认定文档已入库成功。

## 5. 文档入库与一致性

入库流程：上传原件 → 保存哈希和持久任务 → worker 领取 → 校验原件哈希 → 解析分块 → 保存解析产物 → 计算向量 → 写入索引 → SQL 保存切片与关键词 → 激活版本。

1. 上传接口接受 PDF、DOCX、PPTX、XLSX、HTML、Markdown、TXT、CSV，默认上限 50MB；创建文档和任务后返回。持久任务由独立 worker 处理，上传成功不等于索引就绪。
2. TXT 按 UTF-8 读取，`SentenceSplitter(chunk_size=512, chunk_overlap=64)` 分块。其他格式使用 Docling，并由 `HybridChunker` 按 512 token 上限分块、补充结构上下文。这里是 token 限制，不是 512 个汉字。来源包括章节、页码、provenance、元素引用和切片序号；不支持的解析结果不会静默切换解析器。
3. 切片 ID 使用 `{version}_{chunk_index}`。每个切片通过 jieba `cut_for_search` 生成空格分隔的 `keywords`，并记录向量维度到元数据。
4. SQLite 路径先向 Chroma 写向量，再在 SQL 事务中写切片并更新 `active_version`。FTS5 由同事务触发器维护。Chroma 和 SQL 之间没有分布式事务，未激活 / 残留向量由有效版本过滤和维护任务处理。
5. PostgreSQL 路径不写 Chroma，向量与切片一起保存到 SQL。新版本激活后删除旧 SQL 切片，并持久化旧版本清理任务。

入库任务的主要状态为 `queued → processing → staged → ready`；失败根据尝试次数进入 `retrying` / `failed`。文档另外显示 `parsing`、`indexing` 等阶段。普通单文档任务可立即激活；全库批次等待全部 staged 后统一激活。

默认 worker 顺序处理，每轮轮询间隔 3 秒，重试任务等待至少 15 秒，processing 超过 15 分钟可重新领取；单次 `ingest` 包装超时为 840 秒，最多尝试三次。`CancelledError` 可能来自超时或取消，单凭持久错误类别不能判断具体原因。

Chroma 的阻塞操作通过 `asyncio.to_thread` 执行。线程写入被取消时不会自动停止，`write_vectors` 使用 shield 并等待其结束后再进入清理，避免清理后线程又写回孤立向量。修改异步处理时需要保留这个约束。

## 6. 检索流程与得分

### 6.1 公共范围与模式

`KnowledgeRetriever(user_id, kb_ids, top_k=6, mode='hybrid', min_similarity=None)` 通过异步 `aretrieve` 使用；同步 `_retrieve` 明确报错。输出数量限制为 1～12。

所有候选基于 SQL 范围：切片与文档都属于当前用户、知识库在授权集合内，并且 `chunk.version == document.active_version`。API 和 Agent 工具还需检查资源所有权，不能将前端传入的 ID 直接当作权限。

| 模式 | 行为 |
| --- | --- |
| `hybrid` | 关键词 + 按模型分组的向量召回；向量分组异常时记录关键词降级警告 |
| `vector` | 仅向量召回；模型配置、嵌入或索引异常直接失败，不降级 |
| `keyword` | 不计算查询向量；使用关键词候选，仍可经过可选重排 |

### 6.2 关键词与向量召回

关键词：jieba 搜索分词 → 去重并保留含字母 / 数字 / 中文等 `isalnum` 字符的 token → 最多 32 个 token。SQLite 使用 OR 组合的 FTS5 查询和 BM25 排序，最多 40 条。PostgreSQL 使用 `plainto_tsquery('simple', ...)` 和 `ts_rank`，最多 40 条；该多词查询通常要求词项共同匹配，与 SQLite 的 OR 语义不同，跨数据库迁移需要重新评测。

向量：从有效 SQL 切片读取不同 `embedding_profile`，为每组解析对应的旧 / 当前模型，用该模型计算问题向量，并校验同组已存向量维度。

- Chroma 查询过滤 `user_id`、`kb_id in kb_ids`、`version in versions`，每组最多 40 个候选；由距离换算 `similarity = 1 - distance` 并过滤阈值。之后再次通过 SQL 有效版本和 profile 范围读取正文。
- PostgreSQL 在对应 SQL 范围内按余弦距离排序，并在查询中应用阈值，每组最多 40 条；当前输出元数据中的 `vector_similarity` 为 `None`。
- 当前 Chroma 过滤不是逐个 `(doc_id, active_version)` 配对，而是版本集合加最终 SQL 校验。大量残留或暂存向量可能占据候选额度、降低召回，需要维护任务清理。
- SQL 有有效分组却完全没有 Chroma 命中时，报告索引缺失；有命中但全部低于阈值时返回空向量候选。部分缺失不一定触发警告，应通过修复核对。

### 6.3 融合与重排

每个模型的向量结果列表和关键词结果列表作为独立排名，以切片 ID 去重，按以下公式累加 RRF 得分：

```text
score(chunk) = Σ 1 / (60 + rank)，rank 从 1 开始
```

融合取前 40 条，再调用可选重排，最终返回 `top_k`。RRF 得分不是余弦相似度，也不是相关概率；关键词命中不受向量阈值约束。仅向量模式的最终 `score` 仍是融合流程中的排名分数。

重排接口使用 20 秒超时，POST JSON 为 `model`、`query`、`documents`、`top_n`，期望响应 `results: [{index, relevance_score}]`。适配器校验索引、重复项、有限得分和非空结果，再按得分排序；失败记录警告并退回融合前 `top_k`。其他供应商协议需在重排适配层转换。

### 6.4 诊断与证据

检索诊断提供 `requested_mode`、`effective_mode`、`warnings`、`vector_candidates`、`keyword_candidates`、`min_similarity`、`score_type`、`profiles`、`returned`、`elapsed_ms`。`effective_mode` 根据实际候选标记为 hybrid / vector / keyword / empty；没有向量候选不一定意味着服务异常，也可能是阈值过滤。

返回节点包含正文，以及 `doc_id`、`kb_id`、`version`、`chunk_index`、`retrieval_sources`、`vector_similarity` 和来源元数据。`read_chunk` 校验用户、授权知识库和有效版本后返回命中切片及前后各一个邻居。新增索引实现时应保持这些证据字段稳定。

## 7. 重建、模型迁移与索引修复

| 操作 | 是否重新解析 / 嵌入 | 适用情形 |
| --- | --- | --- |
| 单文档重建 | 是 | 重试失败文档、重新生成单文档索引 |
| 全库重建 | 是 | 更换嵌入模型、批量更新分块规则 |
| 修复索引 | 否 | SQL 有有效切片与向量，但 Chroma 缺失 / 残留或 FTS5 需重建 |
| 清理任务 | 否 | 删除文档或版本切换后的物理数据清理 |

全库重建固定加密的模型配置快照，避免任务执行期间默认模型变化导致批次混用。使用 `index_batch_id` 阻止同库上传、删除和单文档重建；全部文档 staged 后在一个 SQL 事务中切换，任一任务耗尽重试则整批失败，保留旧有效版本。激活或失败后清空任务模型快照。

检索不会直接用新默认模型查询旧向量，而是通过 `for_profile` 在当前用户配置的 embedding 模型中寻找旧指纹。迁移验收完成前应保留旧模型配置；缺失旧模型时混合模式降级到关键词，纯向量模式报错。普通上传 / 单文档重建没有全库批次的固定模型快照，应避免处理过程中随意修改配置。

`repair_index` 从 SQL 有效切片按 `(profile, dimension)` 分组，补回缺失向量，并按用户 / 知识库清理无效 ID；保护 queued / retrying / processing / staged 任务版本，然后重建 FTS5。SQL 切片或原始向量丢失、模型空间变化、分块规则变化不能靠修复解决。PostgreSQL 路径目前只统计检查切片，不执行 Chroma / FTS5 修复。

删除与版本切换写入持久 `MaintenanceJob`。清理限定具体文档 / 版本，不能删除仍有效的文档版本或其他文档共享的原件；失败最多尝试五次，耗尽后可通过接口重新提交。历史聊天证据快照不随索引删除自动清除。

## 8. API 与本地运行

以下接口均需认证，前缀为 `/api/knowledge`。

| 方法与路径 | 用途 |
| --- | --- |
| `POST /bases/{kb_id}/documents/upload` | 上传原件并创建入库任务 |
| `POST /documents/{doc_id}/reindex` | 单文档重建 |
| `POST /bases/{kb_id}/reindex` | 全库重建 / 模型迁移 |
| `GET /bases/{kb_id}/jobs` | 入库任务状态和错误 |
| `GET /documents/{doc_id}/chunks` | 有效版本切片分页预览 |
| `POST /bases/{kb_id}/search` | 检索调试，返回候选与 diagnostics |
| `GET /chunks/{chunk_id}` | 获取有效切片 |
| `POST /bases/{kb_id}/repair` | 提交索引修复任务 |
| `GET /maintenance` | 维护任务状态和结果 |
| `POST /maintenance/{job_id}/retry` | 重新提交 failed 维护任务 |

检索调试请求示例：

```json
{
  "query": "华东区域的折扣审批要求是什么？",
  "top_k": 6,
  "mode": "hybrid",
  "min_similarity": 0.25
}
```

注意：`RetrievalProbe.min_similarity` 当前固定默认 0.25；调试接口会将其传入 Retriever。因此更改环境阈值不会改变省略该字段的调试请求。直接构造 Retriever 且未指定阈值时，才采用 `RETRIEVAL_MIN_SIMILARITY`。

在仓库根目录启动默认 worker：

```bash
cd backend
venv/bin/python -m app.workers.local
```

API、迁移及前端的完整启动方式见 [README](../README.md)。只启动 API 而不运行 worker，会使默认数据库队列中的入库和维护任务无法推进。

## 9. 中文能力、验证与排障

当前中文适配包括 jieba 文档 / 查询分词、结构化分块、语义与关键词混合召回及可选重排。Chroma 接收数值向量，中文语义能力主要取决于嵌入模型；框架支持中文不等于具体业务召回已达标。

评测应覆盖同义改写、简称、专有词、数字条件、长段落 / 表格、跨段答案及无答案问题。修改 jieba 词典后，需要重新生成已存 `keywords` 和全文索引；只改查询侧分词会造成不一致。分块 token 预算也需验证是否适配所选嵌入模型。

从仓库根目录运行已有测试：

```bash
backend/venv/bin/python -m pytest backend/tests/test_knowledge_lifecycle.py -q
```

测试覆盖 Chroma 写入与检索、批次切换、失败保留旧版本、缺失索引修复、清理、关键词降级与接口契约；模型调用使用测试替身，不能证明外部服务可用或中文语义效果达标。可选 PostgreSQL 测试见 [test_postgres_integration.py](../backend/tests/test_postgres_integration.py)，按该文件的环境条件配置后运行。

真实模型验收工具使用当前用户模型配置。smoke 模式在临时数据库 / 存储中运行，但测试文本仍会发送到所配置的外部端点；以下命令是人工验收入口，编写文档本身不执行真实调用。

```bash
backend/venv/bin/python backend/scripts/validate_knowledge.py --smoke --user-id USER_ID --output /tmp/knowledge-smoke.json
# 可选：同时验收 Agent 的真实对话模型、检索与引用
backend/venv/bin/python backend/scripts/validate_knowledge.py --smoke --agent --user-id USER_ID --output /tmp/knowledge-agent-smoke.json
# 将示例中的问题和文档 ID 替换为实际标注，再分别比较三个检索模式
backend/venv/bin/python backend/scripts/validate_knowledge.py --user-id USER_ID --kb-id KB_ID --cases docs/knowledge_eval.example.json --mode hybrid --output /tmp/knowledge-eval.json
```

评测输出包含文档级 Recall@K、MRR 和无答案检索准确率，不能替代答案正确率与引用一致性的业务验收。评测样例见 [knowledge_eval.example.json](knowledge_eval.example.json)。

| 现象 | 优先检查 |
| --- | --- |
| 文档持续 queued | worker 是否运行、API / worker 数据库是否一致 |
| 解析失败或 CancelledError | 原件格式、Docling 依赖与模型缓存、超时和进程取消；尚不能归因于 Chroma |
| 嵌入失败 | 当前用户模型类型、地址、Key、模型是否支持 embeddings、接口限制 |
| 向量维度不一致 | 端点是否换模型 / 参数；用原模型恢复或重建，不能补零强行兼容 |
| 索引缺失 | SQL 是否有有效切片，Chroma 路径是否一致；提交修复并查看结果 |
| 有结果但伴随关键词降级 | 查看 warnings，确认旧 profile 对应模型仍配置且可调用 |
| Chroma 有向量但检索为空 | SQL 有效版本、归属、所选知识库、阈值及孤立条目 |
| 删除后物理向量仍存在 | 维护任务及重试状态；SQL 过滤应已阻止访问 |

备份 / 恢复需保证 SQL、原件、解析产物和加密密钥的配套关系；Chroma 可在 SQL 向量完整时修复。默认本地目录不构成多机共享或高可用方案。

## 10. 新增与修改的约束

1. 新增嵌入供应商优先保持 `EmbeddingProvider.embed(list[str]) → list[list[float]]` 的顺序、数量和有限数值校验。需要不同协议时增加显式适配，不让索引层选择模型。
2. 更换向量数据库需覆盖写入、带范围过滤的打分查询、文档 / 版本删除、ID 核对和孤立条目清理，并更新 ingestion、retriever、maintenance 的数据库分支。当前 `VectorIndex` 是具体 Chroma 适配器，尚不是统一多后端接口。
3. 保持 SQL 有效版本作为最终可见性判断，不能只信任向量库元数据。维持用户 / 知识库过滤和 SQL 回查；新增权限维度需贯穿 API、Agent、SQL 与索引。
4. 修改分块、模型版本或影响向量空间的参数时，明确重建策略。不得用新模型查询旧向量，也不得仅因维度一致就合并空间。
5. 调整召回数量、阈值、RRF 权重或重排时，同步检查 Retriever、请求 Schema、Agent 调用、评测脚本及前端参数，保留得分类型和降级诊断。
6. 修改任务并发、取消、激活或清理时，保留旧版本可用性和幂等性，验证取消写入、批次失败、修复保护处理中版本及删除范围。
7. 按改动范围运行现有测试，再用真实中文标注集比较 vector / keyword / hybrid。替换基础设施不能只验证接口返回成功，还需验证权限、版本、删除、修复和证据来源。
8. 引入远程向量服务、多机 worker、缓存或新的模型指纹格式时，补充迁移、兼容和恢复方案，同步更新本文与 [架构说明](architecture.md)。
