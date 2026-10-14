"""Docling structure -> HybridChunker -> LlamaIndex TextNodes, without silent fallback."""
from pathlib import Path
from app.infrastructure.tokenization import encoding
from llama_index.core.schema import TextNode
from llama_index.core.node_parser import SentenceSplitter


def parse_document(path: Path, version: str) -> tuple[list[TextNode], dict, str]:
    if path.suffix.lower() == '.txt':
        text = path.read_text(encoding='utf-8')
        if not text.strip():
            raise ValueError('文档没有可提取内容')
        splitter = SentenceSplitter(chunk_size=512, chunk_overlap=64)
        nodes = [TextNode(id_=f'{version}_{i}', text=s, metadata={'parser': 'native_text', 'chunk_index': i})
                 for i, s in enumerate(splitter.split_text(text))]
        return nodes, {'parser': 'native_text', 'text': text}, text
    from docling.document_converter import DocumentConverter
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
    result = DocumentConverter().convert(str(path))
    if result.status.value != 'success':
        raise ValueError('Docling 未完整解析文档，请检查格式与解析模型')
    document = result.document
    chunker = HybridChunker(tokenizer=OpenAITokenizer(tokenizer=encoding(), max_tokens=512))
    nodes = []
    for i, chunk in enumerate(chunker.chunk(dl_doc=document)):
        content = chunker.contextualize(chunk=chunk)
        if not content.strip():
            continue
        provenance = [p.model_dump(mode='json') for item in chunk.meta.doc_items for p in item.prov]
        metadata = {'parser': 'docling', 'chunk_index': i, 'headings': chunk.meta.headings or [],
                    'pages': sorted({p['page_no'] for p in provenance}), 'provenance': provenance,
                    'element_refs': [item.self_ref for item in chunk.meta.doc_items]}
        nodes.append(TextNode(id_=f'{version}_{i}', text=content, metadata=metadata))
    if not nodes:
        raise ValueError('Docling 未提取到有效切片')
    return nodes, document.export_to_dict(), document.export_to_markdown()
