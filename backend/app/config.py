from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / '.env'), extra='ignore')
    PROJECT_NAME: str = '经管之星 BusinessLens'
    SECRET_KEY: str = 'development-only-change-before-deploy'
    APP_DATABASE_USER: str = 'rag_app'
    APP_DATABASE_PASSWORD: str = 'rag'
    CREDENTIAL_KEY: str = ''
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    DATABASE_URL: str = f'sqlite+aiosqlite:///{BASE_DIR.parent}/storage-v2/app.db'
    STORAGE_DIR: Path = BASE_DIR.parent / 'storage-v2'
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ''
    LANGSMITH_TRACING: bool = False
    LANGSMITH_ENDPOINT: str = ''
    LANGSMITH_API_KEY: str = ''
    LANGSMITH_PROJECT: str = 'rag-langgraph'
    TASK_BACKEND: str = 'database'
    REDIS_URL: str = 'redis://localhost:6379/0'
    STT_API_BASE: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    STT_API_KEY: str = ''
    STT_MODEL: str = 'qwen3-asr-flash'
    AGENT_MAX_STEPS: int = Field(default=64, ge=1, le=1000)
    AGENT_MAX_TOOL_CALLS: int = Field(default=128, ge=1, le=2000)
    AGENT_TIMEOUT: int = Field(default=900, ge=1)
    AGENT_WORKER_CONCURRENCY: int = Field(default=5, ge=1, le=32)
    AGENT_DEFAULT_CONTEXT_TOKENS: int = Field(default=131072, ge=8192)
    AGENT_CONTEXT_TOKENS: int | None = Field(default=None, ge=8192)
    AGENT_MAX_OUTPUT_TOKENS: int = Field(default=8192, ge=256)
    AGENT_TOOL_PRUNE_TRIGGER_TOKENS: int = Field(default=100000, ge=512)
    AGENT_SUMMARY_TRIGGER_TOKENS: int = Field(default=200000, ge=512)
    AGENT_SUMMARY_KEEP_TOKENS: int = Field(default=32000, ge=256)
    AGENT_COMPACTION_BUFFER_RATIO: float = Field(default=0.1, ge=0.01, le=0.5)
    # Zero disables the optional cost/volume guard; context capacity remains enforced.
    AGENT_MAX_TOTAL_TOKENS: int = Field(default=0, ge=0)
    AGENT_TOOL_OUTPUT_TOKENS: int = Field(default=3000, ge=256)
    AGENT_CONTEXT_SAFETY_TOKENS: int = Field(default=2048, ge=256)
    AGENT_RECENT_TOOL_RESULTS: int = Field(default=8, ge=0)
    AGENT_MAX_IDENTICAL_TOOL_CALLS: int = Field(default=3, ge=1)
    SQL_TIMEOUT_MS: int = 15000
    SQL_MAX_ROWS: int = 200
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024
    CORS_ORIGINS: list[str] = ['http://localhost:5173']

    @property
    def USER_STORAGE_DIR(self) -> Path:
        return self.STORAGE_DIR / 'users'

settings = Settings()
