"""Real-provider acceptance in an isolated store, or relevance evaluation on an owned KB.

Smoke: python backend/scripts/validate_knowledge.py --smoke --agent --output report.json
Eval:  python backend/scripts/validate_knowledge.py --user-id ID --kb-id ID --cases cases.json
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def metrics(cases, results):
    recalls, reciprocals, negatives = [], [], []
    for case, hits in zip(cases, results, strict=True):
        if case.get('no_answer'):
            negatives.append(int(not hits))
            continue
        expected = set(case['expected_doc_ids'])
        ranked = list(dict.fromkeys(hit['doc_id'] for hit in hits))
        recalls.append(len(expected.intersection(ranked))/len(expected))
        reciprocals.append(next((1/(i+1) for i, key in enumerate(ranked) if key in expected), 0))
    return {'recall_at_k': sum(recalls)/len(recalls) if recalls else None,
        'mrr': sum(reciprocals)/len(reciprocals) if reciprocals else None,
        'no_answer_accuracy': sum(negatives)/len(negatives) if negatives else None,
        'positive_cases': len(recalls), 'negative_cases': len(negatives)}


async def smoke_child(args):
    from app.infrastructure.credentials import decrypt, encrypt
    from app.config import settings
    secrets = json.loads(decrypt(Path(args.config).read_text()))
    env = {**os.environ, 'DATABASE_URL': settings.DATABASE_URL, 'STORAGE_DIR': str(settings.STORAGE_DIR)}
    migrated = subprocess.run([sys.executable, '-m', 'alembic', '-c', str(BACKEND/'alembic.ini'), 'upgrade', 'head'],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    if migrated.returncode:
        raise RuntimeError('isolated migration failed')
    import httpx
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.models.config import AppConfig
    from app.models.platform import IngestionJob
    from app.security.auth import create_access_token
    from app.ingestion.pipeline import ingest
    from app.retrieval.retriever import KnowledgeRetriever
    from main import app
    models = []
    for kind, config in secrets.items():
        models.append({'id':config['model_id'], 'type':kind, 'base_url':config['base_url'],
            'api_key':encrypt(config['api_key'])})
    value = {'available_models':models,'default_embedding_model':secrets['embedding']['model_id']}
    if 'llm' in secrets:
        value['default_model'] = secrets['llm']['model_id']
    async with AsyncSessionLocal() as db:
        user = User(username='isolated-acceptance',hashed_password='unused')
        db.add(user); await db.flush()
        db.add(AppConfig(user_id=user.id,config_key='model_setting',config_value=json.dumps(value),is_enabled=True))
        await db.commit(); uid = user.id
    headers = {'Authorization':'Bearer '+create_access_token({'sub':uid})}
    checks = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',timeout=240) as client:
        kb = (await client.post('/api/knowledge/bases',headers=headers,json={'name':'隔离验收'})).json()['id']
        samples = [('policy.md','# 华东折扣政策\n\n华东客户折扣为 5%，需要主管审批。\n\n| 审批人 | 折扣 |\n| --- | --- |\n| 主管 | 5% |\n'.encode(),'华东客户折扣需要谁审批？'),
            ('warehouse.txt','仓库盘点规则：每月最后一个工作日盘点库存，差异由仓库负责人签字。'.encode(),'库存盘点时间和签字人是什么？')]
        if args.document:
            if not args.query:
                raise ValueError('文档验收需要 --query')
            path=Path(args.document)
            samples.append((path.name,path.read_bytes(),args.query))
        for filename, content, query in samples:
            response = await client.post(f'/api/knowledge/bases/{kb}/documents/upload',headers=headers,
                files={'file':(filename,content,'application/octet-stream')})
            response.raise_for_status()
            doc_id = response.json()['id']
            async with AsyncSessionLocal() as db:
                job_id = await db.scalar(select(IngestionJob.id).where(IngestionJob.doc_id==doc_id))
            await ingest(job_id)
            state = (await client.get(f'/api/knowledge/documents/{doc_id}/status',headers=headers)).json()
            retriever = KnowledgeRetriever(uid,[kb])
            hits = await retriever.aretrieve(query)
            rank = next((i+1 for i,hit in enumerate(hits) if hit.node.metadata['doc_id']==doc_id),None)
            vector_verified = any(hit.node.metadata['doc_id']==doc_id and 'vector' in hit.node.metadata['retrieval_sources'] for hit in hits)
            checks.append({'format':Path(filename).suffix, 'status':state['status'], 'chunks':state['chunk_count'],
                'expected_document_rank':rank, 'vector_retrieval_verified':vector_verified, 'diagnostics':retriever.diagnostics})
        agent_result = None
        if args.agent:
            workspace = await client.post('/api/workspaces', headers=headers, json={'name':'知识验证空间','kb_ids':[kb]})
            workspace.raise_for_status()
            response = await client.post('/api/chat/stream',headers=headers,json={
                'query':'请先检索知识库，说明华东客户的折扣和审批要求，并引用来源。','workspace_id':workspace.json()['id'],
                'model':secrets['llm']['model_id']})
            response.raise_for_status()
            events = [json.loads(frame[6:]) for frame in response.text.strip().split('\n\n') if frame.startswith('data: ')]
            citations = [event for event in events if event['type']=='citations' and event.get('items')]
            answer = ''.join(event.get('content','') for event in events if event['type']=='chunk')
            failures=[]
            for event in events:
                if event['type']=='tool_end' and event.get('is_error'):
                    try:
                        category=json.loads(event.get('result','')).get('category','tool_error')
                    except (ValueError, AttributeError):
                        category='tool_error'
                    failures.append({'tool':event.get('name'),'category':category})
            agent_result = {'status':events[-1].get('status'), 'has_citations':bool(citations),
                'has_source_reference':'[来源 ' in answer, 'policy_answer_supported':'5%' in answer or '百分之五' in answer,
                'tool_failures':failures}
        passed = all(check['status']=='ready' and check['expected_document_rank'] and
            check['vector_retrieval_verified'] and not check['diagnostics']['warnings'] for check in checks)
        if agent_result:
            passed = passed and agent_result['status']=='completed' and all(agent_result[k] for k in
                ('has_citations','has_source_reference','policy_answer_supported'))
        return {'passed':bool(passed), 'isolated_storage':True, 'real_embedding':True,
            'embedding_model':secrets['embedding']['model_id'], 'checks':checks, 'agent':agent_result}


async def prepare_smoke(args):
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.config import settings
    from app.models.user import User
    from app.infrastructure.embeddings import EmbeddingProvider
    from app.services.llm_service import LLMService
    from app.infrastructure.credentials import encrypt
    async with AsyncSessionLocal() as db:
        ids = [args.user_id] if args.user_id else list((await db.scalars(select(User.id))).all())
        candidates = []
        for uid in ids:
            try:
                embedding = (await EmbeddingProvider.for_user(db,uid)).config
                secrets = {'embedding':embedding}
                if args.agent:
                    secrets['llm'] = await LLMService.get_model_config(db,uid)
                candidates.append(secrets)
            except ValueError:
                continue
        if len(candidates)!=1:
            raise ValueError('需指定唯一已配置模型的用户：--user-id')
    with tempfile.TemporaryDirectory(prefix='rag-real-acceptance-') as root:
        config = Path(root)/'models.enc'
        config.touch(mode=0o600)
        config.write_text(encrypt(json.dumps(candidates[0])))
        env = {**os.environ, 'DATABASE_URL':f'sqlite+aiosqlite:///{root}/app.db', 'STORAGE_DIR':root+'/storage',
            'CREDENTIAL_KEY':settings.CREDENTIAL_KEY,'SECRET_KEY':settings.SECRET_KEY,'TASK_BACKEND':'database'}
        command = [sys.executable,str(Path(__file__)), '--smoke-child','--config',str(config)]
        if args.agent:
            command.append('--agent')
        if args.document:
            command.extend(['--document',str(Path(args.document).resolve()),'--query',args.query or ''])
        child = await asyncio.create_subprocess_exec(*command,env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
        try:
            stdout, _ = await asyncio.wait_for(child.communicate(),timeout=900)
        except asyncio.TimeoutError:
            import signal
            os.killpg(child.pid,signal.SIGTERM)
            await child.wait()
            raise TimeoutError('验收超时')
        # The child only prints a sanitized JSON result; SDK bodies/credentials are never forwarded.
        try:
            report = json.loads(stdout)
        except ValueError:
            raise RuntimeError('隔离验收进程失败，未产生报告')
        return report


async def evaluate(args):
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.knowledge import KnowledgeBase
    from app.retrieval.retriever import KnowledgeRetriever
    if not all((args.user_id,args.kb_id,args.cases)):
        raise ValueError('评测需要 --user-id、--kb-id 和 --cases')
    async with AsyncSessionLocal() as db:
        if not await db.scalar(select(KnowledgeBase.id).where(KnowledgeBase.id==args.kb_id,KnowledgeBase.user_id==args.user_id)):
            raise ValueError('知识库不存在或用户无权访问')
    cases=json.loads(Path(args.cases).read_text())
    if not isinstance(cases,list) or not cases:
        raise ValueError('评测集必须是非空数组')
    results, diagnostics = [], []
    for case in cases:
        if not isinstance(case.get('query'),str) or not case['query'].strip() or (not case.get('no_answer') and not case.get('expected_doc_ids')):
            raise ValueError('每条需要 query，以及 expected_doc_ids 或 no_answer=true')
        retriever=KnowledgeRetriever(args.user_id,[args.kb_id],args.top_k,mode=args.mode,min_similarity=args.min_similarity)
        hits=await retriever.aretrieve(case['query'])
        results.append([{'doc_id':hit.node.metadata['doc_id'],'chunk_id':hit.node.node_id} for hit in hits])
        diagnostics.append(retriever.diagnostics)
    return {'mode':args.mode,'top_k':args.top_k,'min_similarity':args.min_similarity,
        'metrics':metrics(cases,results),'diagnostics':diagnostics,'results':results,
        'note':'文档级指标；无答案准确率只衡量检索是否为空，不代表生成答案准确率'}


async def main(args):
    started=time.monotonic()
    try:
        report=await (smoke_child(args) if args.smoke_child else prepare_smoke(args) if args.smoke else evaluate(args))
        report['elapsed_seconds']=round(time.monotonic()-started,2)
    except Exception as exc:
        report={'passed':False,'error_category':type(exc).__name__}
    finally:
        from app.database import engine
        await engine.dispose()
    if args.output:
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 1 if report.get('passed') is False else 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--agent',action='store_true')
    parser.add_argument('--smoke-child',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--config',help=argparse.SUPPRESS)
    parser.add_argument('--user-id')
    parser.add_argument('--kb-id')
    parser.add_argument('--cases')
    parser.add_argument('--document',help='额外验收文件；仅上传到临时知识库，内容会发送到已配置嵌入服务')
    parser.add_argument('--query',help='额外文件的检索验收问题')
    parser.add_argument('--mode',choices=['hybrid','keyword','vector'],default='hybrid')
    parser.add_argument('--min-similarity',type=float,default=0.25)
    parser.add_argument('--top-k',type=int,choices=range(1,13),default=6)
    parser.add_argument('--output')
    sys.exit(asyncio.run(main(parser.parse_args())))
