"""Read configured providers; validate public fixtures without writing application data."""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import AsyncSessionLocal, engine
from app.infrastructure.embeddings import EmbeddingProvider
from app.services.llm_service import LLMService
from app.services import frequent_service as svc


async def validate(args):
    async with AsyncSessionLocal() as db:
        provider = await EmbeddingProvider.for_user(db, args.user_id)
        cfg = await LLMService.get_model_config(db, args.user_id)
    samples = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/frequent_questions.json').read_text())
    prior = json.loads(args.output.read_text()) if args.retry_failed and args.output.exists() else {}
    by_label = {item['label']: item for item in prior.get('results', [])}
    pending = [s for s in samples if not by_label.get(s['label'], {}).get('passed')]
    representatives = list(dict.fromkeys(s['representative'] for s in pending if s['representative']))
    vectors = await provider.embed(representatives, timeout=55, max_retries=0) if representatives else []
    indexed = dict(zip(representatives, vectors))
    report = {'llm_model':cfg['model_id'], 'embedding_model':provider.config['model_id'],
        'embedding_profile':provider.profile,'started_at':datetime.now(timezone.utc).isoformat(),
        'concurrency':args.concurrency, 'results':[]}
    results = {}
    semaphore = asyncio.Semaphore(args.concurrency)

    def save():
        report['results'] = [results[i] for i in sorted(results)]
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

    async def run(index, sample):
        previous = by_label.get(sample['label'])
        if previous and previous.get('passed'):
            results[index] = previous
            return
        history = previous.get('attempt_history', [
            {'passed':previous['passed'],'error_code':previous.get('error_code')}]) if previous else []
        async with semaphore:
            for attempt in range(args.attempts):
                try:
                    vector = (await provider.embed([sample['question']], timeout=55, max_retries=0))[0]
                    candidates = [] if sample['representative'] is None else [SimpleNamespace(
                        id='candidate', representative_question=sample['representative'],
                        representative_asked_at=datetime.fromisoformat(sample['representative_asked_at']),
                        embedding=indexed[sample['representative']])]
                    candidates = sorted(candidates, key=lambda g: svc.cosine(vector,g.embedding), reverse=True)[:svc.TOP_K]
                    eligible, matched = await asyncio.wait_for(svc.judge(cfg,sample['question'],datetime.fromisoformat(sample['asked_at']),candidates),svc.MODEL_TIMEOUT)
                    passed = eligible == sample['eligible'] and (matched is not None) == sample['match']
                    result = {**sample,'actual_eligible':eligible,'actual_match':matched is not None,'passed':passed}
                    history.append({'passed':passed,'error_code':None})
                    break  # A semantic mismatch must remain a failure; never retry to obtain a desired classification.
                except Exception as exc:
                    result = {**sample,'passed':False,'error_code':type(exc).__name__}
                    history.append({'passed':False,'error_code':type(exc).__name__})
                    if attempt + 1 < args.attempts:
                        await asyncio.sleep(1)
            result['attempt_history'] = history
            results[index] = result
            save()
            print(f"{len(results)}/{len(samples)} {sample['label']}: {'PASS' if result['passed'] else 'FAIL'}",flush=True)

    await asyncio.gather(*(run(index,sample) for index,sample in enumerate(samples)))
    report['passed'] = sum(r['passed'] for r in results.values())
    report['total'] = len(samples)
    report['status'] = 'passed' if report['passed'] == report['total'] else 'failed'
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    save()
    await engine.dispose()
    return report['status'] == 'passed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--user-id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--retry-failed',action='store_true',help='Keep passing results; retry only failed samples and preserve attempt history')
    parser.add_argument('--concurrency',type=int,choices=range(1,5),default=1)
    parser.add_argument('--attempts',type=int,choices=range(1,4),default=3,help='Retry exceptions only; semantic mismatches are never retried')
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        passed = asyncio.run(validate(args))
    except Exception as exc:
        args.output.write_text(json.dumps({'status':'incomplete', 'error_code':type(exc).__name__,
            'note':'Provider initialization or connection failed; no semantic-quality result.'},ensure_ascii=False,indent=2)+'\n')
        print('Validation incomplete: ' + type(exc).__name__)
        passed = False
    sys.exit(0 if passed else 1)
