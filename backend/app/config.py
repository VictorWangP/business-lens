from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / '.env'), extra='ignore')
    PROJECT_NAME: str = '商析 BusinessLens'
    SECRET_KEY: str = 'development-only-change-before-deploy'
    APP_DATABASE_USER: str = 'rag_app'
    APP_DATABASE_PASSWORD: str = 'rag'
    CREDENTIAL_KEY: str = ''
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    DATABASE_URL: str = f'sqlite+aiosqlite:///{BASE_DIR.parent}/storage-v2/app.db'
    STORAGE_DIR: Path = BASE_DIR.parent / 'storage-v2'
    STORAGE_BACKEND: str = 'local'
    S3_BUCKET: str = ''
    S3_ENDPOINT: str = ''
    S3_REGION: str = 'us-east-1'
    AWS_ACCESS_KEY_ID: str = ''
    AWS_SECRET_ACCESS_KEY: str = ''
    AWS_SESSION_TOKEN: str = ''
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ''
    TASK_BACKEND: str = 'database'
    REDIS_URL: str = 'redis://localhost:6379/0'
    STT_API_BASE: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    STT_API_KEY: str = ''
    STT_MODEL: str = 'qwen3-asr-flash'
    RERANK_API_URL: str = ''
    RERANK_MODEL: str = ''
    RERANK_API_KEY: str = ''
    RETRIEVAL_MIN_SIMILARITY: float = Field(default=0.25, ge=-1, le=1)
    AGENT_MAX_STEPS: int = Field(default=12, ge=1, le=50)
    AGENT_MAX_TOOL_CALLS: int = Field(default=16, ge=1, le=100)
    AGENT_TIMEOUT: int = 180
    AGENT_WORKER_CONCURRENCY: int = Field(default=5, ge=1, le=32)
    AGENT_CONTEXT_TOKENS: int = Field(default=32768, ge=8192)
    AGENT_SUMMARY_TRIGGER_TOKENS: int = Field(default=18000, ge=2000)
    AGENT_SUMMARY_KEEP_TOKENS: int = Field(default=6000, ge=1000)
    AGENT_MAX_TOTAL_TOKENS: int = 64000
    SQL_TIMEOUT_MS: int = 15000
    SQL_MAX_ROWS: int = 200
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024
    CORS_ORIGINS: list[str] = ['http://localhost:5173']

    @property
    def CHROMA_PERSIST_DIR(self) -> Path:
        return self.STORAGE_DIR / "chroma"

    @property
    def USER_STORAGE_DIR(self) -> Path:
        return self.STORAGE_DIR / 'users'

settings = Settings()
