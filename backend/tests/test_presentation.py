"""Chart contracts needed by the CSV demonstrations."""
from decimal import Decimal
from app.analytics.presentation import chart_from_rows


def test_pie_uses_amounts_and_preserves_query_category_order():
    rows=[{'region':'华东','revenue':Decimal('4200.00')},{'region':'华南','revenue':Decimal('3800.00')}]
    chart=chart_from_rows(rows,'地区收入','pie')
    assert chart['type']=='pie' and chart['x_key']=='region'
    assert chart['data']==[{'region':'华东','revenue':4200.0},{'region':'华南','revenue':3800.0}]


def test_numeric_month_dimension_can_generate_line_chart():
    chart=chart_from_rows([{'sign_month':Decimal(1),'total_contract_wan':Decimal('800.0')},
                          {'sign_month':Decimal(2),'total_contract_wan':Decimal('650.0')}],'合同趋势','line')
    assert chart['type']=='line' and chart['y_keys']==['total_contract_wan']
    assert [r['sign_month'] for r in chart['data']]==['1','2']


def test_missing_future_values_are_null_and_negative_series_are_not_pies():
    line=chart_from_rows([{'month':'10月','revenue':Decimal('2.50')},{'month':'11月','revenue':None}],'收入','line')
    assert line['data'][1]['revenue'] is None
    assert chart_from_rows([{'line':'AI','yoy':-90},{'line':'存储','yoy':5}],'同比','pie')['type']=='bar'
    assert chart_from_rows([{'region':'华北','value':0}],'零金额','pie')['type']=='bar'


def test_single_scalar_is_not_a_category_chart():
    assert chart_from_rows([{'total':Decimal('0.30')}],'销售额','pie') is None
