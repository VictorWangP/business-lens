from pathlib import Path
from app.ingestion.parser import parse_document

def test_docling_markdown_preserves_heading_and_table(tmp_path):
    path = tmp_path / 'policy.md'
    path.write_text('# 华东折扣政策\n\n主管审批后生效。\n\n| 客户 | 折扣 |\n| --- | --- |\n| 华东 | 5% |\n', encoding='utf-8')
    nodes, structure, markdown = parse_document(path, 'version')
    assert nodes and structure and '华东' in markdown
    assert all(n.metadata['parser'] == 'docling' for n in nodes)
    assert any('华东折扣政策' in n.metadata['headings'] for n in nodes)
    assert any('5%' in n.page_content for n in nodes)
    assert all(n.metadata['element_refs'] for n in nodes)

# Conversion models are downloaded by Docling on first use. Keep this opt-in so
# the ordinary unit suite does not unexpectedly download model artifacts.
import os
import pytest

@pytest.mark.skipif(os.environ.get('RAG_DOCLING_PDF_ACCEPTANCE')!='1',reason='Explicit Docling PDF/OCR acceptance required')
@pytest.mark.parametrize('scanned',[False,True])
def test_docling_pdf_and_scanned_pdf(tmp_path,scanned):
    path=tmp_path/('scanned.pdf' if scanned else 'text.pdf')
    if scanned:
        from PIL import Image,ImageDraw,ImageFont
        image=Image.new('RGB',(1200,800),'white');draw=ImageDraw.Draw(image)
        font=ImageFont.load_default(size=40)
        draw.text((70,100),'Revenue policy',font=font,fill='black')
        draw.text((70,200),'East region discount: 5 percent.',font=font,fill='black')
        draw.text((70,300),'Manager approval is required.',font=font,fill='black')
        image.save(path,'PDF',resolution=150)
    else:
        stream=b'BT /F1 24 Tf 70 700 Td (Revenue policy) Tj 0 -60 Td (East region discount: 5 percent.) Tj 0 -60 Td (Manager approval is required.) Tj ET'
        objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
        data=b'%PDF-1.4\n';offsets=[0]
        for i,obj in enumerate(objects,1):offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
        start=len(data);data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
        for offset in offsets[1:]:data+=f'{offset:010d} 00000 n \n'.encode()
        data+=f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode();path.write_bytes(data)
    documents,structure,text=parse_document(path,'pdf-acceptance')
    assert 'approval' in text.lower() and '5' in text
    assert structure and documents
    assert any(1 in document.metadata['pages'] for document in documents)
    assert any(document.metadata['provenance'] for document in documents)
