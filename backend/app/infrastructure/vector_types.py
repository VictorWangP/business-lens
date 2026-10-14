from sqlalchemy import JSON

def vector_type():
    try:
        from pgvector.sqlalchemy import Vector
        return Vector().with_variant(JSON(), 'sqlite')
    except ImportError:
        return JSON()
