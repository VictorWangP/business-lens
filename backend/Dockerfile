FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
WORKDIR /app
COPY requirements.lock requirements.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
# PostgreSQL business connectors are part of the deployed application too.
RUN pip install --no-cache-dir -r requirements-postgres.txt
# Download the tokenizer at build time; runtime needs no tokenizer network access.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
    && chmod -R a+rX /opt/tiktoken-cache \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir /data && chown app:app /data
COPY . .
USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
