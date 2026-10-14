"""Validate every CSV using the application's actual importer and SQL policy, in temporary storage."""
import hashlib
import json
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
from app.config import settings
from app.application.tabular import import_file
from app.analytics.sql_policy import validate_sql
from app.analytics.presentation import chart_from_rows, json_value
import duckdb


def main():
    root=BACKEND.parent/'datasets/demo_csv'
    manifest=json.loads((root/'manifest.json').read_text())
    scenarios=json.loads((root/'demo_queries.json').read_text())
    original_storage=settings.STORAGE_DIR
    report={'external_model_called':False,'files':[],'queries':[]}
    try:
        with tempfile.TemporaryDirectory(prefix='rag-csv-check-') as temp:
            settings.STORAGE_DIR=Path(temp)
            for entry in manifest['files']:
                content=(root/entry['file']).read_bytes()
                assert hashlib.sha256(content).hexdigest()==entry['sha256'],entry['file']
                imported=import_file('validation-user',entry['file'],content)
                assert imported['row_count']==entry['rows'],entry['file']
                with duckdb.connect(str(imported['path']),read_only=True,config={'enable_external_access':'false','threads':'2','memory_limit':'256MB'}) as conn:
                    assert conn.execute('SELECT COUNT(*) FROM dataset').fetchone()[0]==entry['rows']
                    if entry['file'] in {'01_sales_orders.csv','03_monthly_sales.csv'}:
                        result=conn.execute('SELECT SUM(revenue_yuan),SUM(cost_yuan),SUM(gross_profit_yuan) FROM dataset').fetchone()
                        assert result[0]==Decimal(manifest['checks']['sales_revenue_yuan'])
                        assert result[1]+result[2]==result[0]
                    if entry['file']=='04_unit_targets.csv':
                        assert conn.execute('SELECT SUM(actual_revenue_yuan) FROM dataset').fetchone()[0]==Decimal(manifest['checks']['sales_revenue_yuan'])
                    if entry['file']=='02_receivables.csv':
                        assert conn.execute('SELECT COUNT(*) FROM dataset WHERE invoice_amount_yuan != paid_amount_yuan+outstanding_amount_yuan').fetchone()[0]==0
                    if entry['file']=='08_inventory_snapshots.csv':
                        assert conn.execute('SELECT COUNT(*) FROM dataset WHERE stock_quantity != reserved_quantity+available_quantity').fetchone()[0]==0
                        counts=conn.execute('SELECT COUNT(*) FROM dataset GROUP BY snapshot_date').fetchall()
                        assert len({r[0] for r in counts})==1
                    for scenario in [s for s in scenarios if s['file']==entry['file']]:
                        sql=validate_sql(scenario['sql'],'main',['dataset'],dialect='duckdb')
                        result=conn.execute(sql)
                        columns=[c[0] for c in result.description]
                        rows=[dict(zip(columns,row)) for row in result.fetchall()]
                        assert rows and len(rows)<=50,scenario['id']
                        chart=chart_from_rows(rows,scenario['question'],scenario['chart_type'])
                        if scenario['chart_type']!='none':
                            assert chart and chart['type']==scenario['chart_type'],scenario['id']
                        if 'expected_scalar' in scenario:
                            assert str(next(iter(rows[0].values())))==str(scenario['expected_scalar']),scenario['id']
                        report['queries'].append({'id':scenario['id'],'file':entry['file'],'rows':len(rows),
                            'chart_type':chart['type'] if chart else None,'sample':json_value(rows[:2])})
                report['files'].append({'file':entry['file'],'rows':entry['rows'],'import':'passed'})
                shutil.rmtree(imported['path'].parent)
                print('PASS',entry['file'])
    finally:
        settings.STORAGE_DIR=original_storage
    assert len(report['queries'])==len(scenarios)
    report['total_rows']=manifest['total_rows']
    (root/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f'Validated {len(report["files"])} imports and {len(report["queries"])} SQL scenarios. Original application/business databases were not modified.')

if __name__=='__main__':main()
