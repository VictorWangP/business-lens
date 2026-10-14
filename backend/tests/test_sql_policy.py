import pytest
from app.analytics.sql_policy import validate_sql

@pytest.mark.parametrize('sql', [
    'DELETE FROM sales', 'SELECT * FROM sales; SELECT * FROM sales',
    'SELECT * FROM private.sales', 'SELECT * FROM pg_catalog.pg_authid',
    'SELECT * FROM secret', 'SELECT pg_sleep(10) FROM sales',
    "SELECT dblink('x','DELETE FROM sales') FROM sales",
    'WITH changed AS (DELETE FROM sales RETURNING *) SELECT * FROM changed',
    'SELECT * INTO backup FROM sales', 'SELECT * FROM sales FOR UPDATE',
    'SELECT custom.sum(amount) FROM sales', 'SELECT amount::regclass FROM sales',
    "SELECT * FROM sales UNION SELECT * FROM secret",
    "SELECT * FROM sales WHERE EXISTS (SELECT 1 FROM secret)",
    'SELECT * FROM generate_series(1, 100)', 'SELECT 1',
])
def test_reject_untrusted_sql(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, 'reporting', ['sales'])

@pytest.mark.parametrize('sql', [
    'SELECT region, SUM(amount) FROM sales GROUP BY region',
    'WITH x AS (SELECT * FROM sales) SELECT COUNT(*) FROM x',
    'SELECT * FROM sales WHERE amount > 0 AND region IS NOT NULL LIMIT 999999',
    "SELECT DATE_TRUNC('month', order_date), COUNT(*) FROM sales GROUP BY 1",
    'SELECT SUM(amount) FROM sales WHERE order_date >= :start_date AND order_date < :end_date',
])
def test_approved_queries_are_scoped_and_bounded(sql):
    rewritten = validate_sql(sql, 'reporting', ['sales'])
    assert '"reporting"."sales"' in rewritten
    assert rewritten.endswith('LIMIT 201')
    assert '%(' not in rewritten


def test_quoted_cte_cannot_shadow_real_relation():
    with pytest.raises(ValueError):
        validate_sql('WITH sales AS (SELECT * FROM secret) SELECT * FROM sales', 'reporting', ['sales'])
