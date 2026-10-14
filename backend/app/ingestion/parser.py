"""Docling's official LangChain loader preserves structured document provenance."""
from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.infrastructure.tokenization import encoding


def parse_document(path: Path, version: str) -> tuple[list[Document], dict, str]:
    if path.suffix.lower() == '.txt':
        text = path.read_text(encoding='utf-8')
        splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name='cl100k_base', chunk_size=512, chunk_overlap=64)
        documents = splitter.create_documents([text], [{'parser': 'native_text'}])
        parsed = {'parser': 'native_text', 'text': text}
    else:
        from docling.document_converter import DocumentConverter
        from docling.chunking import HybridChunker
        from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
        from langchain_docling import DoclingLoader
        result = DocumentConverter().convert(str(path))
        if result.status.value != 'success':
            raise ValueError('Docling 未完整解析文档，请检查格式与解析模型')
        # The loader consumes the already converted result; no second conversion.
        class ConvertedDocument:
            def convert(self, **kwargs):
                return result
        documents = DoclingLoader(str(path), converter=ConvertedDocument(),
            chunker=HybridChunker(tokenizer=OpenAITokenizer(tokenizer=encoding(), max_tokens=512))).load()
        parsed, text = result.document.export_to_dict(), result.document.export_to_markdown()
        for document in documents:
            meta = document.metadata.pop('dl_meta', {})
            items = meta.get('doc_items', [])
            provenance = [prov for item in items for prov in item.get('prov', [])]
            document.metadata = {'parser': 'docling', 'headings': meta.get('headings') or [],
                'pages': sorted({prov['page_no'] for prov in provenance}),
                'provenance': provenance, 'element_refs': [item['self_ref'] for item in items]}
    documents = [doc for doc in documents if doc.page_content.strip()]
    if not documents:
        raise ValueError('文档没有可提取内容')
    for i, document in enumerate(documents):
        document.id = f'{version}_{i}'
        document.metadata['chunk_index'] = i
    return documents, parsed, text
