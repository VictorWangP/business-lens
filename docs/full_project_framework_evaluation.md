# 文档 RAG + 关系数据库问数：完整项目框架评比

日期：2026-10-14　状态：**待审核的架构评估，未实施**

## 1. 范围与结论

范围恢复为：文档解析、分块、索引、检索、关系数据库问数，以及 Agent 编排、历史会话、摘要、上下文压缩、工具调用、前端事件和暂停恢复。延续“不考虑现有迁移复杂性，只看目标方案优劣”的评估前提。

**对当前已知功能，主推荐仍为 LangGraph/LangChain 负责唯一 Agent 与会话状态，Docling 负责文档解析和结构分块，检索通过成熟 loader/vector-store/retriever 接口实现。LlamaIndex 是复杂 RAG 的可选专用组件，而不是重新接管整个 Agent 的必选项。**

如果产品明确需要 LlamaIndex 的多级/递归检索、节点关系、检索组合或 ingestion 组件，并能据此减少实现或改善实际检索效果，则采用混合方案：**LlamaIndex 只负责 RAG，LangGraph/LangChain 继续负责唯一 Agent。** 不让两套框架同时管理会话和执行。

这是按当前需求覆盖和长期维护边界作出的工程判断；没有进行解析、检索准确率、延迟或故障恢复的对照实验，不能宣称某框架天然更准确。

本文件补充 [纯 SQL 选型](sql_agent_framework_evaluation.md) 和 [综合重构提案](ai_chat_refactor_proposal.md)。本轮仅查阅源码/官方资料并更新文档，没有安装依赖、修改业务代码或执行测试。

## 2. 先分清“文档能力”来自哪里

文档系统包含不同职责，不能全部归为一个 RAG 框架：

| 层 | 实际职责 | 适合承担的组件 |
| --- | --- | --- |
| 解析/OCR | PDF 阅读顺序、表格、页面、图片和结构 | Docling，或按文件验收选择其他解析服务 |
| 分块/元数据 | 块边界、标题、页面与原文定位 | Docling HybridChunker、成熟 splitter/parser |
| ingestion | 转换、嵌入、缓存、去重、写入 | 框架 pipeline/集成 + 应用发布管理 |
| 检索 | 关键词/向量召回、融合、重排、上下文扩展 | 搜索后端和 Retriever 组件 |
| 业务管理 | 权限、来源版本、重建、删除、任务状态 | 应用与数据库，不能只依赖默认框架行为 |
| Agent | 选择检索/SQL 工具、澄清、生成回答 | 唯一编排框架 |
| 会话 | checkpoint、摘要、interrupt、恢复、前端流 | Agent 状态底座 + 标准服务/runtime |

Docling 官方同时提供 LangChain 与 LlamaIndex 集成。因此复杂 PDF 解析能力不是只有选择 LlamaIndex 才能获得。[Docling 集成](https://docling-project.github.io/docling/integrations/)、[LangChain DoclingLoader](https://docs.langchain.com/oss/python/integrations/document_loaders/docling)

LlamaParse/LlamaCloud 是可另行选择的产品，与开源 LlamaIndex 框架不是同一项能力或部署约束；本报告不把采用框架等同于必须采用托管服务。

## 3. 当前代码的实际依赖

本轮检查发现：

- `backend/app/ingestion/parser.py`：结构文档由 Docling DocumentConverter 和 HybridChunker 处理，输出页面、标题与 provenance；LlamaIndex 主要提供 TextNode，以及 TXT 的 SentenceSplitter。
- `backend/app/ingestion/pipeline.py`：应用自行组织嵌入、SQL/Chroma 写入、staged/active 版本、批次激活、失败与清理任务，没有使用 LlamaIndex IngestionPipeline 管理这些流程。
- `backend/app/retrieval/retriever.py`：继承 BaseRetriever，但关键词查询、向量分组、权限/有效版本过滤、RRF、重排调用和降级主要由应用实现。
- `backend/app/infrastructure/embeddings.py` 和 `vector_index.py`：直接调用嵌入接口与 Chroma，包含模型指纹、维度和有效结果检查。
- `backend/app/services/rag_service.py`：把检索节点转换为 CitationItem，再交给 Agent。

因此，当前加入知识库功能并不能证明“离开 LlamaIndex 就失去文档能力”；目前也没有大量依赖其高层 ingestion/query-engine 功能。这个发现用于判断目标抽象是否必要，不是以迁移成本为理由选型。

当前 RAG 有较复杂的业务约束，如多嵌入模型分组、索引版本发布和引用追溯。这些约束两套框架都需要明确适配，不能简单用几行通用 RAG 示例替换。

## 4. 三个完整候选方案

### A. LlamaIndex 主导完整项目

Docling + LlamaIndex ingestion/retrievers + FunctionAgent/Workflows + Memory + Context/DBOS + AG-UI + assistant-ui。

优点：文档处理、节点、检索和 Agent 使用同一生态；复杂 RAG 组件较集中；Workflows 也能处理分支、人工交互和持久化执行。

代价：当前所需的摘要、会话服务与 UI 接入需要协调 Memory、Context、持久化 runtime 和协议适配；不能认为采用一个框架就自动统一所有生命周期。

### B. LangGraph/LangChain 主导，Docling 独立解析

Docling/DoclingLoader + embeddings/vector-store/retriever + LangChain create_agent/middleware + LangGraph checkpoint + assistant-ui 官方 runtime。

优点：会话和执行状态在一个体系内；原生摘要 middleware 和专用 UI adapter；文档与 SQL 都成为普通受权工具；无需为了常规 RAG 再维护另一套节点/检索框架抽象。

代价：复杂 RAG 仍需组合合适的 retriever/搜索后端；loaders 或 vector-store adapter 不自动实现版本发布、精细溯源和跨存储一致性。采用此方案不是继续保留所有当前自定义 RRF/索引代码，而是逐项用成熟组件替换可替换部分。

### C. 专业分工：LlamaIndex RAG + LangGraph/LangChain Agent

Docling + LlamaIndex ingestion/retrievers → 受权知识服务 → LangGraph/LangChain 唯一 Agent → assistant-ui。

优点：能采用 LlamaIndex 的专用 RAG 组件，同时复用 LangGraph/LangChain 会话、摘要、interrupt 和 UI 能力；适合知识检索持续演进的系统。

代价：需要一个有限的 Document/Node→Evidence 转换边界、两套依赖的版本兼容和 tracing；若 LlamaIndex 只是被用来包节点或传列表，则新增抽象没有足够收益。

## 5. 能力比较

下表是定性适配判断，不是测试评分。A 包含完整持久化方案，C 不包含第二套 Agent。

| 维度 | A：LlamaIndex 主导 | B：LangGraph/LangChain + Docling | C：LlamaIndex RAG + LangGraph |
| --- | --- | --- | --- |
| 复杂 PDF/OCR/表格解析 | 取决于 Docling/解析服务 | 同左 | 同左 |
| 结构分块与页面定位 | 可用成熟 parser/Docling | 可用 Docling/loader | 可用成熟 parser/Docling |
| ingestion 转换/缓存/去重 | 专用组件集中 | 有集成与索引接口，需组合 | 可使用 LlamaIndex 专用组件 |
| 常规向量/混合检索 | 能满足 | 能满足 | 能满足，但不必为此增加框架 |
| 多级/递归/组合检索 | 相关组件集中 | 可实现，需按需求选组件 | 分工灵活，适合复杂 RAG |
| 权限/版本/原文引用 | 应用明确实现与验收 | 同左 | 同左，边界必须保留元数据 |
| SQL 问数 | 能满足 | 能满足 | SQL 仍由统一 Agent 调用 |
| 会话摘要与上下文管理 | 现代 Memory + 摘要策略 | 成熟 middleware + thread state | 与 B 相同 |
| checkpoint/人工恢复 | Context/快照或 DBOS | 原生 checkpoint/interrupt | 与 B 相同 |
| assistant-ui 对接 | 可通过 AG-UI | 有专用 adapter，也可 AG-UI | 与 B 相同 |
| 概念/依赖边界 | 一套生态，内部生命周期仍需协调 | 单一 Agent/消息体系，解析独立 | 两套生态，需明确知识服务边界 |
| 当前已知需求的净适配 | 可行 | **优先推荐** | 需要专用 RAG 收益才能成为首选 |

LlamaIndex 提供 IngestionPipeline 的 transformations/cache/docstore 去重等能力，以及 QueryFusionRetriever 等检索组合；这些是实在的复用点，不应笼统忽略。[ingestion API](https://developers.llamaindex.ai/python/framework-api-reference/ingestion/)、[融合检索](https://developers.llamaindex.ai/python/framework/integrations/retrievers/reciprocal_rerank_fusion/)

LangChain 提供文档加载、嵌入、向量库和 Retriever 集成；DoclingLoader 支持结构化 chunk 导出及元数据提取。它足以构成当前常见 RAG 基础，并非只擅长工具调用。[知识库示例](https://docs.langchain.com/oss/python/langchain/knowledge-base)、[DoclingLoader](https://docs.langchain.com/oss/python/integrations/document_loaders/docling)

## 6. 为什么主推荐 B，而不是默认混合

### 6.1 文档能力不会消除会话需求

多轮 SQL/RAG 混合问答仍需要摘要、状态持久化、澄清、故障恢复和 UI 工具生命周期。LangGraph/LangChain 对这组需求的优势仍适用。[持久化](https://docs.langchain.com/oss/python/langgraph/persistence)、[摘要 middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization)

### 6.2 当前没有明确必须依赖 LlamaIndex 的检索特性

已知需求主要是结构解析、带元数据分块、混合召回、重排、相邻原文、引用和版本/权限。这些可以由 Docling、搜索后端及成熟 Retriever 接口承担。版本与权限自定义不会仅因换 RAG 框架消失。

### 6.3 混合方案需要证明净收益

同一模型、解析器、切分、检索数据和重排器下，使用两个框架不保证更高召回率。若 C 只是把 B 的 Document 转为 TextNode 再转回来，应选择 B；若 C 能直接替代多套复杂检索实现，混合才有实际价值。

因此当前推荐 B；确认以下需求并取得组件复用/质量证据后，可将 C 升为首选：

- 文档树、父子块或递归检索成为主要需求。
- 多索引/多检索策略组合，需要实质使用 LlamaIndex 的现成组件。
- 需要特定 query/index/postprocessor 能力，等价替代的长期实现更复杂。
- ingestion cache、节点关系和元数据抽取能明显减少重复实现，同时满足隔离与版本要求。

若未来产品主要是复杂知识问答、会话控制需求较轻，A 也合理；不能把 LlamaIndex 视为不支持持久化。当前官方有 DBOS durable runtime，但与使用 LangGraph 相比仍是另一种能力组合。[LlamaIndex DBOS](https://developers.llamaindex.ai/python/llamaagents/workflows/dbos/)

## 7. 推荐分层与运行方式

### 7.1 文档入库链路独立运行

上传/来源同步 → 文档哈希与版本 → Docling 解析 → 结构分块/元数据 → 嵌入与索引 → staged 校验 → 激活有效版本。

- 长耗时解析、OCR、嵌入不放在每次聊天请求中重复执行。
- DoclingLoader 默认 DOC_CHUNKS 可保留结构分块；不要先转整份 Markdown 再任意切碎。使用 metadata extractor 显式保留 pages、provenance、element refs，并验证导出未丢失定位信息。
- 不因套用 loader 就取消应用索引发布事务、嵌入模型指纹、维度检查和删除清理。
- pipeline cache/docstore 的默认去重不等于用户/空间隔离和 SQL/向量库原子切换。缓存 key 必须纳入内容、parser/chunker/embedding 配置以及隔离策略。
- 如果选择搜索后端原生混合检索，验证其词法/向量得分、中文行为和权限过滤；不要再同时维护一套无必要的应用级融合。

### 7.2 只有一个问答 Agent

LangGraph/LangChain Agent 调用以下受控工具即可：授权 schema/指标、只读 SQL、知识搜索、原文片段读取。无需为 SQL 和文档各建一套完整 Agent。

Agent 根据问题调用 SQL、文档或二者；“是否需要知识库”的路由可以是工具选择或少量确定性节点，不必一开始引入多 Agent 协作。

最终答案由同一个结构化输出/业务校验出口生成，区分数据库事实、文档规定和分析推断。RAG 服务不先生成一遍答案，再交主 Agent 重写。

### 7.3 统一知识工具边界

无论 B 还是 C，知识服务对 Agent 返回小型 Evidence 对象：

- chunk/document/source ID、来源版本与检索时间；
- 内容片段、页码/标题/原文定位；
- 检索方式、得分类型与必要的降级警告。

用户/空间/授权来源来自可信运行上下文，不由模型随意提供。工具返回预算受限证据和可读取原文的 ID；全文与原始解析产物保存在知识服务。

框架 Document/TextNode 只在知识服务内部使用，跨边界不携带 live retriever、LLM client 或另一套 Memory。

## 8. 混合方案 C 的明确禁区

若采用 C，需要满足以下约束才不会增加重复实现：

1. LangGraph 是唯一会话和执行状态所有者；LlamaIndex 不再运行另一套 FunctionAgent/聊天 Memory。
2. 只通过 Retriever/必要的原文读取接口取证；默认不调用会再次生成答案的 QueryEngine。
3. 摘要只有 LangChain 一套；不同时保存两套会话摘要与指代状态。
4. 一个前端 runtime 和事件协议；LlamaIndex 检索事件由知识服务诊断记录，不直接再开一条 UI stream。
5. 解析、嵌入和检索由知识链路负责，避免两套框架重复嵌入、写索引或自行选择默认模型。
6. 所有 QueryFusionRetriever 子检索器均带同样的权限/有效版本过滤；不能检索后才在回答阶段剔除越权内容。
7. LlamaIndex 默认多 query 生成等组件会产生额外模型调用；按需要禁用/配置，不把“更多组件”当作免费提升。
8. 知识索引与图 checkpoint 是不同数据生命周期，各自清理；恢复前复核来源权限/版本，旧 checkpoint 不构成永久访问许可。

在这些边界下，混合只是一个检索组件实现，而不是两套 Agent 平台嵌套。

## 9. 所有方案都无法省略的业务管理

- 文件与解析产物、章节/表格/图片的精确溯源。
- 授权来源过滤、有效版本和删除可见性。
- 嵌入模型变更、重建、回滚、批次发布、缓存和重试。
- SQL 只读/授权视图/超时/成本限制，以及精确数据表格与图表能力。
- 长对话摘要的事实保留、旧数据失效和完整聊天归档。
- 暂停状态、resume 授权、后台调度和浏览器断线重放。

因此，不能以框架名或“几行代码”的 demo 判断生产方案复杂度。替换成熟组件后仍保留这些规则，是必要业务实现。

## 10. 如何确认 B 与 C 的选择

审核后的对照评估应固定解析器、embedding、reranker、文件集和问题集，避免把换模型的收益归给框架：

- 解析：扫描件、表格、阅读顺序、页码/坐标溯源。
- 检索：Recall@k/nDCG、证据充分性、中文术语/精确编号和多跳问题。
- 生命周期：重复入库、更新/删除、embedding 切换、失败后旧版本可用。
- 问答：文档+SQL 联合引用、纠正后的多轮指代、图表与原始数值一致。
- 运行：长对话压缩、interrupt、崩溃恢复、重连和权限撤销。
- 工程：实际替代的自定义算法/适配数量、额外 LLM 调用、延迟和维护中的状态所有者。

本轮尚未执行这些验收，因此不提供虚构的效果或代码缩减百分比。

## 11. 最终排序与审核建议

**按当前功能与“减少通用自定义实现”的目标：B 为首选，C 为有明确复杂检索收益时的升级选择，A 为文档/RAG 主导型产品的备选。**

审核建议：

1. Agent 和会话底座选择 LangGraph/LangChain。
2. 文档解析继续选择经文件验收的 Docling，优先成熟集成；解析器与 Agent 框架解耦。
3. 检索层保持一个稳定 Evidence 接口，首期选能覆盖需求的成熟组件。
4. 不因加入文档就强制保留/引入 LlamaIndex；若其专用 RAG 组件能带来实际收益，则按 C 的严格边界使用。
5. assistant-ui 展示、SQL 安全、授权、精确数据与来源验证继续按综合方案实施；尚未授权开始迁移。
