# 知识库验收记录

验收日期：2026-10-10（Asia/Shanghai）。所有现场验收在独立临时数据库、Chroma 和文件目录内执行，结束后移除；现有知识库未写入验收内容。模型凭据未写入报告。

- `knowledge-smoke.json`：真实嵌入与对话模型，Markdown/TXT 上传、解析、索引、检索及引用通过。
- `knowledge-pdf-smoke.json`：增加工作区已有架构说明 PDF；PDF 就绪，17 个切片，预期文档检索排名第一，真实 Agent 完成且无工具错误。
- `knowledge-pdf-smoke-initial.json`：首次 PDF 链路同样成功，但 Agent 状态为 partial。该次未采集工具错误类别，不能确定原因；保留失败记录，避免将一次通过解读为稳定性保证。

这些结果证明了当前配置下的链路连通和少量样例命中，不是大规模业务准确率或 SLA 验收。PDF 首次运行约 222 秒，后续约 22 秒，包含不同的解析模型缓存状态和模型调用行为，不能当作严格性能对比。未覆盖全部扫描件、复杂表格及所有支持格式。可选 PostgreSQL/Celery 未做现场验收。

使用 `backend/scripts/validate_knowledge.py` 和 `docs/knowledge_eval.example.json` 建立自有标注集，可比较混合、向量、关键词检索的文档级 Recall@K、MRR 和无答案检索准确率。模型回答是否完整、是否忠于证据仍需单独评估。
