"""Presentation is derived from actual result rows, never invented growth rates."""
from decimal import Decimal
from datetime import date, datetime


def json_value(value):
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53-1:
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def chart_from_rows(rows: list[dict], title: str, chart_type: str = 'bar') -> dict | None:
    if not rows or len(rows) > 50:
        return None
    numeric = [k for k in rows[0] if any(isinstance(r.get(k), (int, float, Decimal)) and not isinstance(r.get(k), bool) for r in rows)]
    categories = [k for k in rows[0] if k not in numeric]
    if not categories and len(numeric) >= 2:
        # SQLite reference views sometimes return month/year as a numeric dimension.
        dimensions = {'sign_month', 'month', 'year', 'week', 'day', '月份', '年份'}
        categories = [key for key in numeric if key.lower() in dimensions][:1]
        numeric = [key for key in numeric if key not in categories]
    if not numeric or not categories:
        return None
    x = categories[0]
    kind = chart_type if chart_type in {'bar', 'line', 'pie'} else 'bar'
    if kind == 'pie' and (any(r.get(numeric[0]) is None or r[numeric[0]] < 0 for r in rows)
                          or sum(r[numeric[0]] for r in rows) <= 0):
        kind = 'bar'
    return {'type': kind, 'title': title, 'x_key': x, 'y_keys': numeric[:2],
            'data': [{x: str(r.get(x, '')), **{k: float(r[k]) if r.get(k) is not None else None for k in numeric[:2]}} for r in rows]}


def metrics_from_rows(rows: list[dict], unit: str = '') -> list[dict]:
    if len(rows) != 1:
        return []
    return [{'label': key, 'value': f'{value}{(" " + unit) if unit else ""}'}
            for key, value in rows[0].items()
            if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)]
