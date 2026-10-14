"""Reproducible synthetic ICT business CSV pack. Never modifies the reference SQLite database."""
import argparse
import calendar
import csv
import hashlib
import json
import random
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AS_OF = date(2026, 10, 9)
START = date(2024, 1, 1)
SEED = 20261010


def money(cents):
    return format(Decimal(cents) / 100, '.2f')


def pct(numerator, denominator):
    return format((Decimal(numerator) * 100 / denominator).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f') if denominator else '0.00'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'datasets/demo_csv')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    source = (ROOT / 'storage/business_data.db').resolve()
    conn = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    units = [dict(r) for r in conn.execute('SELECT unit_id,unit_name,region,province,city FROM dim_operating_unit ORDER BY unit_id')]
    products = [dict(r) for r in conn.execute('SELECT product_id,model_code,line_name,category,list_price_yuan,cost_price_yuan FROM dim_product ORDER BY product_id')]
    industries = [r[0] for r in conn.execute('SELECT industry_name FROM dim_industry ORDER BY industry_id')]
    channels = ['直销', '经销商', '电商', '合作伙伴']
    months = [date(y,m,1) for y in range(2024,2027) for m in range(1,13) if date(y,m,1)<=AS_OF]
    monthly_weights = [(1.4 if m.month in {3,6,9,12} else 1) * (min(calendar.monthrange(m.year,m.month)[1],AS_OF.day) / 31 if m.year==AS_OF.year and m.month==AS_OF.month else 1) for m in months]
    manifest = {'synthetic': True, 'seed': SEED, 'reference_database':'storage/business_data.db',
                'actual_data_start':str(START), 'actual_data_end':str(AS_OF), 'currency':'CNY',
                'note':'All generated records are synthetic; reference_* files export the existing demonstration database. Forecast dates may exceed actual_data_end.', 'files':[]}

    def write(filename, rows, grain, description, origin='synthetic'):
        if not rows:
            raise ValueError('Empty dataset: '+filename)
        path = output / filename
        fields = list(rows[0])
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        entry = {'file':filename,'rows':len(rows),'columns':fields,'bytes':path.stat().st_size,
                 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'grain':grain,'description':description,'origin':origin}
        assert len(rows)<=100_000 and entry['bytes']<=50*1024*1024 and len(fields)<=200
        manifest['files'].append(entry)
        print(f'{filename}: {len(rows):,} rows, {entry["bytes"]:,} bytes')

    def sales_date():
        m=rng.choices(months,weights=monthly_weights,k=1)[0]
        end=min(calendar.monthrange(m.year,m.month)[1], AS_OF.day) if m.year==AS_OF.year and m.month==AS_OF.month else calendar.monthrange(m.year,m.month)[1]
        return date(m.year,m.month,rng.randint(1,end))

    aggregates=defaultdict(lambda: [0]*8)
    unit_month=defaultdict(lambda: [0]*5)
    sales=[]
    invoices=[]
    total_revenue=total_cost=total_orders=0
    for i in range(80_000):
        d=sales_date(); u=rng.choice(units); p=rng.choice(products); industry=rng.choice(industries); channel=rng.choices(channels,[40,35,10,15])[0]
        quantity=rng.choices([1,2,3,5,10,20],[22,22,18,18,15,5])[0]
        if d.year==2026 and p['line_name']=='智能计算产品线': quantity=max(1,quantity//2)
        if d.year==2026 and d.month>=7 and u['region']=='华东': quantity=max(1,quantity*7//10)
        discount_bp=rng.randint(200,1600)+(400 if channel=='经销商' else 0)
        list_cents=int(Decimal(str(p['list_price_yuan']))*100)
        price_cents=(list_cents*(10_000-discount_bp)+5000)//10_000
        amount=quantity*price_cents
        status=rng.choices(['已完成','已取消','已退货'],[93,4,3])[0]
        revenue=amount if status=='已完成' else 0
        cost=quantity*int(Decimal(str(p['cost_price_yuan']))*100) if status=='已完成' else 0
        refund=amount if status=='已退货' else 0
        customer=f'CUST-{rng.randint(1,4000):05d}'
        row={'order_id':f'ORD-{i+1:07d}','order_date':str(d),'year_month':d.strftime('%Y-%m'),
            'year':d.year,'quarter':f'{d.year}-Q{(d.month-1)//3+1}','unit_name':u['unit_name'],'region':u['region'],
            'province':u['province'],'city':u['city'],'industry_name':industry,'customer_id':customer,
            'customer_name':f'模拟客户-{customer[5:]}','customer_segment':rng.choice(['大型客户','中型客户','小型客户']),
            'model_code':p['model_code'],'line_name':p['line_name'],'category':p['category'],'channel':channel,
            'order_status':status,'quantity':quantity,'unit_price_yuan':money(price_cents),'discount_pct':pct(discount_bp,10_000),
            'order_amount_yuan':money(amount),'revenue_yuan':money(revenue),'cost_yuan':money(cost),
            'gross_profit_yuan':money(revenue-cost),'refund_amount_yuan':money(refund)}
        sales.append(row)
        a=aggregates[(row['year_month'],u['region'],p['line_name'])]
        for j,value in enumerate([1,int(status=='已完成'),quantity if status=='已完成' else 0,revenue,cost,revenue-cost,refund,int(status=='已退货')]): a[j]+=value
        b=unit_month[(row['year_month'],u['unit_name'],u['region'])]
        for j,value in enumerate([1,int(status=='已完成'),revenue,cost,revenue-cost]):b[j]+=value
        total_revenue+=revenue;total_cost+=cost;total_orders+=1
        if status=='已完成' and len(invoices)<30_000:
            due=d+timedelta(days=rng.choice([30,60,90,120]))
            overdue=max(0,(AS_OF-due).days)
            paid_bp=rng.choices([10000,7000,3000,0],[80,8,6,6])[0] if overdue else rng.choice([0,3000,7000,10000])
            paid=(revenue*paid_bp+5000)//10000; outstanding=revenue-paid
            aging='已结清' if outstanding==0 else '未到期' if overdue==0 else '1-30天' if overdue<=30 else '31-60天' if overdue<=60 else '61-90天' if overdue<=90 else '90天以上'
            invoices.append({'invoice_id':f'INV-{len(invoices)+1:07d}','order_id':row['order_id'],'invoice_date':str(d),
                'year_month':row['year_month'],'due_date':str(due),'as_of_date':str(AS_OF),'region':u['region'],
                'unit_name':u['unit_name'],'industry_name':industry,'customer_id':customer,'channel':channel,
                'invoice_amount_yuan':money(revenue),'paid_amount_yuan':money(paid),'outstanding_amount_yuan':money(outstanding),
                'overdue_amount_yuan':money(outstanding if overdue else 0),'overdue_days':overdue if outstanding else 0,
                'aging_bucket':aging,'collection_status':'已结清' if outstanding==0 else '逾期' if overdue else '未到期'})
    write('01_sales_orders.csv',sales,'一行一个模拟订单','销售额、毛利、同比、区域/行业/型号/渠道、退款、客户排行')
    write('02_receivables.csv',invoices,'一行一张模拟发票；对应销售明细中的部分已完成订单','应收、回款、账龄、逾期与客户风险；截至固定快照日期')

    monthly=[]
    for (month,region,line),a in sorted(aggregates.items()):
        monthly.append({'year_month':month,'month_start':month+'-01','region':region,'line_name':line,
            'order_count':a[0],'completed_order_count':a[1],'units_sold':a[2],'revenue_yuan':money(a[3]),
            'cost_yuan':money(a[4]),'gross_profit_yuan':money(a[5]),'gross_margin_pct':pct(a[5],a[3]),
            'refund_amount_yuan':money(a[6]),'returned_order_count':a[7]})
    write('03_monthly_sales.csv',monthly,'月份 × 大区 × 产品线；从 01 精确汇总','小文件快速演示月度趋势、产品结构、区域销售和毛利率')
    targets=[]
    for (month,unit,region),a in sorted(unit_month.items()):
        target=max(1,a[2]*rng.randint(80,150)//100)
        targets.append({'year_month':month,'month_start':month+'-01','unit_name':unit,'region':region,
            'target_revenue_yuan':money(target),'actual_revenue_yuan':money(a[2]),'revenue_gap_yuan':money(a[2]-target),
            'completion_rate_pct':pct(a[2],target),'gross_profit_yuan':money(a[4]),'order_count':a[0],
            'completed_order_count':a[1],'period_status':'月内快照' if month=='2026-10' else '完整月'})
    write('04_unit_targets.csv',targets,'月份 × 经营单元；实绩来自 01，目标独立模拟','目标/实绩对比、缺口、达成率、经营单元排行')

    opportunities=[]
    campaign_stats=defaultdict(lambda:[0,0,0,0])
    for i in range(24_000):
        d=sales_date();u=rng.choice(units);industry=rng.choice(industries);channel=rng.choice(channels)
        stage=rng.choices(['线索','需求确认','方案评估','商务谈判','已赢单','已丢单'],[14,16,15,13,28,14])[0]
        probabilities={'线索':10,'需求确认':25,'方案评估':50,'商务谈判':75,'已赢单':100,'已丢单':0}
        amount=rng.randint(5_000_00,5_000_000_00)
        close=d+timedelta(days=rng.randint(15,120));active=stage not in {'已赢单','已丢单'}
        campaign=f'{d:%Y-%m}|{channel}|{industry}'
        a=campaign_stats[(d.strftime('%Y-%m'),channel,industry)]
        for j,v in enumerate([1,int(stage=='已赢单'),int(stage=='已丢单'),amount if stage=='已赢单' else 0]):a[j]+=v
        opportunities.append({'opportunity_id':f'OPP-{i+1:07d}','created_date':str(d),'year_month':d.strftime('%Y-%m'),
            'region':u['region'],'unit_name':u['unit_name'],'industry_name':industry,'channel':channel,'campaign_id':campaign,
            'stage':stage,'estimated_amount_yuan':money(amount),'win_probability_pct':probabilities[stage],
            'weighted_pipeline_yuan':money(amount*probabilities[stage]//100 if active else 0),
            'won_contract_amount_yuan':money(amount if stage=='已赢单' else 0),'expected_close_date':str(close),
            'closed_date':str(min(AS_OF,close)) if not active else '', 'as_of_date':str(AS_OF),
            'age_days':(AS_OF-d).days,'is_open':int(active),'is_stale':int(active and (AS_OF-d).days>120)})
    write('05_crm_opportunities.csv',opportunities,'一行一个模拟商机；与销售订单不逐笔关联','漏斗、赢单率、渠道转化、预测管道、长期停滞商机')
    campaigns=[]
    for (month,channel,industry),a in sorted(campaign_stats.items()):
        spend=rng.randint(300_000,5_000_000)
        campaigns.append({'campaign_id':f'{month}|{channel}|{industry}','year_month':month,'channel':channel,
            'industry_name':industry,'spend_yuan':money(spend),'lead_count':a[0],'won_count':a[1],
            'lost_count':a[2],'won_contract_amount_yuan':money(a[3]),'win_rate_pct':pct(a[1],a[0]),
            'cost_per_lead_yuan':money(spend//a[0]),'contract_roas':format(Decimal(a[3])/spend,'.4f')})
    write('06_marketing_campaigns.csv',campaigns,'月份 × 渠道 × 行业；商机数与赢单金额来自 05','营销成本、获客成本、合同口径 ROAS 与渠道对比')

    projects=[]
    for i in range(6000):
        d=sales_date();u=rng.choice(units);industry=rng.choice(industries)
        deadline=d+timedelta(days=rng.randint(60,360));completed=rng.random()<.65 and deadline<=AS_OF
        actual=min(AS_OF,deadline+timedelta(days=rng.randint(-20,100))) if completed else None
        delay=max(0,((actual or AS_OF)-deadline).days)
        due=(actual or deadline)+timedelta(days=60)
        contract=rng.randint(1_000_000,800_000_000)
        paid_bp=rng.choice([3000,6000,8000,10000]) if completed else rng.choice([0,1000,3000])
        collected=(contract*paid_bp+5000)//10000;outstanding=contract-collected
        overdue=max(0,(AS_OF-due).days) if outstanding else 0
        risk='高风险' if delay>60 or overdue>90 else '中风险' if delay>15 or overdue>30 else '低风险'
        reason='交付延期及回款逾期' if delay>60 and overdue>90 else '回款逾期' if overdue>90 else '交付延期' if delay>60 else '需关注进度' if risk=='中风险' else '正常'
        projects.append({'project_id':f'PROJ-{i+1:06d}','project_name':f'模拟项目-{i+1:06d}','signed_date':str(d),
            'year_month':d.strftime('%Y-%m'),'unit_name':u['unit_name'],'region':u['region'],'industry_name':industry,
            'stage':'已交付' if completed else '交付中','planned_delivery_date':str(deadline),'actual_delivery_date':str(actual) if actual else '',
            'payment_due_date':str(due),'as_of_date':str(AS_OF),'contract_amount_yuan':money(contract),'collected_amount_yuan':money(collected),
            'uncollected_amount_yuan':money(outstanding),'delivery_delay_days':delay,'payment_overdue_days':overdue,'risk_level':risk,'risk_reason':reason})
    write('07_project_risks.csv',projects,'一行一个模拟项目、固定日期风险快照；与订单不逐笔关联','风险项目、交付延期、回款敞口、经营单元与行业风险排行')

    inventory=[]
    warehouse_regions=['华东','华南','华北','华中','西南','西北','东北']
    days=(AS_OF-date(2025,1,1)).days+1
    combinations=days*len(warehouse_regions)*len(products)
    snapshot_count = min(days, 18_000 // (len(warehouse_regions)*len(products)))
    day_offsets = [i*(days-1)//(snapshot_count-1) for i in range(snapshot_count)]
    combinations = [(day,w,p_index) for day in day_offsets for w in range(len(warehouse_regions)) for p_index in range(len(products))]
    for day,w,p_index in combinations:
        d=date(2025,1,1)+timedelta(days=day);p=products[p_index];qty=rng.randint(5,300)
        if d.year==2026 and p['line_name']=='智能计算产品线':qty=qty*2
        reserved=rng.randint(0,qty);age=rng.randint(1,240);cost=int(Decimal(str(p['cost_price_yuan']))*100)
        inventory.append({'snapshot_date':str(d),'year_month':d.strftime('%Y-%m'),'warehouse':warehouse_regions[w]+'中心仓',
            'region':warehouse_regions[w],'model_code':p['model_code'],'line_name':p['line_name'],'stock_quantity':qty,
            'reserved_quantity':reserved,'available_quantity':qty-reserved,'unit_cost_yuan':money(cost),'stock_value_yuan':money(qty*cost),
            'inventory_age_days':age,'age_bucket':'0-30天' if age<=30 else '31-90天' if age<=90 else '91-180天' if age<=180 else '180天以上',
            'reorder_point':30,'is_slow_moving':int(age>180),'is_stockout_risk':int(qty-reserved<30)})
    inventory.sort(key=lambda r:(r['snapshot_date'],r['warehouse'],r['model_code']))
    write('08_inventory_snapshots.csv',inventory,'日期 × 仓库 × 型号；每个快照日覆盖全部仓库与型号，不构成进销存流水','库存趋势、库龄、滞销、库存结构；不同日期库存金额不可直接累计作为期末库存')

    daily=defaultdict(lambda:[0,0,0])
    regional=defaultdict(lambda:[0,0,0])
    product_mix=defaultdict(lambda:[0,0,0])
    years=defaultdict(lambda:[0,0,0])
    for r in sales:
        cents=int(Decimal(r['revenue_yuan'])*100)
        profit=int(Decimal(r['gross_profit_yuan'])*100)
        daily[r['order_date']][0]+=cents;daily[r['order_date']][1]+=profit;daily[r['order_date']][2]+=1
        years[r['year_month'][5:]][r['year']-2024]+=cents
        if r['year']==2026:
            regional[r['region']][0]+=cents;regional[r['region']][1]+=profit;regional[r['region']][2]+=1
            product_mix[r['model_code']][0]+=cents;product_mix[r['model_code']][1]+=profit
            product_mix[r['model_code']][2]+=r['quantity'] if r['order_status']=='已完成' else 0
    write('09_daily_sales_trend.csv',[{'order_date':day,'year_month':day[:7],'revenue_yuan':money(a[0]),
        'gross_profit_yuan':money(a[1]),'order_count':a[2]} for day,a in sorted(daily.items())],
        '每日；从 01 精确汇总','查询最近 30 天折线图，或按月份再聚合')
    total_2026=sum(a[0] for a in regional.values())
    write('10_region_sales_2026.csv',[{'region':region,'revenue_yuan':money(a[0]),'gross_profit_yuan':money(a[1]),
        'order_count':a[2],'revenue_share_pct':pct(a[0],total_2026),'as_of_date':str(AS_OF)}
        for region,a in sorted(regional.items(),key=lambda item:-item[1][0])],
        '2026 年初至快照日期 × 大区；从 01 汇总','即导即用：7 个大区柱状图、收入份额饼图')
    write('11_product_mix_2026.csv',[{'model_code':model,'revenue_yuan':money(a[0]),'gross_profit_yuan':money(a[1]),
        'units_sold':a[2],'revenue_share_pct':pct(a[0],total_2026),'as_of_date':str(AS_OF)}
        for model,a in sorted(product_mix.items(),key=lambda item:-item[1][0])],
        '2026 年初至快照日期 × 型号；从 01 汇总','产品排行、收入占比、销量和毛利比较')
    write('12_monthly_sales_comparison.csv',[{'month_label':month+'月','revenue_2024_yuan':money(a[0]),
        'revenue_2025_yuan':money(a[1]),'revenue_2026_yuan':money(a[2]) if int(month)<=AS_OF.month else '',
        'status_2026':'完整月' if int(month)<AS_OF.month else '月内快照' if int(month)==AS_OF.month else '尚未发生'}
        for month,a in sorted(years.items())],
        '自然月份；从 01 汇总','跨年双折线；2026 年 10 月仅至 9 日，11/12 月为空而非零')

    views=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]
    for i,view in enumerate(views,1):
        rows=[dict(r) for r in conn.execute('SELECT * FROM "'+view.replace('"','""')+'"')]
        write(f'reference_{i:02d}_{view.removeprefix("view_")}.csv',rows,'保持原演示视图粒度',
              '现有 business_data.db 演示数据快照；保留原预设指标，份额口径须另行核对','existing_demo_database')
    conn.close()
    manifest['checks']={'sales_order_count':total_orders,'sales_revenue_yuan':money(total_revenue),
        'sales_cost_yuan':money(total_cost),'sales_gross_profit_yuan':money(total_revenue-total_cost),
        'monthly_revenue_yuan':money(sum(a[3] for a in aggregates.values())),
        'unit_target_actual_revenue_yuan':money(sum(a[2] for a in unit_month.values())),
        'receivable_invoice_amount_yuan':format(sum(Decimal(r['invoice_amount_yuan']) for r in invoices),'.2f'),
        'receivable_paid_amount_yuan':format(sum(Decimal(r['paid_amount_yuan']) for r in invoices),'.2f'),
        'receivable_outstanding_amount_yuan':format(sum(Decimal(r['outstanding_amount_yuan']) for r in invoices),'.2f')}
    manifest['total_rows']=sum(f['rows'] for f in manifest['files'])
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Total: {len(manifest["files"])} CSV files, {manifest["total_rows"]:,} rows')

if __name__=='__main__':
    main()
