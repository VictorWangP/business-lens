from app.config import settings

def enqueue_document(job_id: str):
    if settings.TASK_BACKEND == 'celery':
        from app.workers.tasks import ingest_document
        ingest_document.delay(job_id)
    # The local database worker polls durable jobs. No broker is required.
