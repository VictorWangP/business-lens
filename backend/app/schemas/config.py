from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict

class WelcomeConfig(BaseModel):
    is_enabled: bool = True
    greeting: str = "你好"
    assistant_name: str = "我是经管之星·AI问数助手"
    description: str = "欢迎使用智能AI问数，您可以向我咨询经营数据、报表分析相关问题。"
    questions: List[str] = Field(default_factory=list)

class NextQuestionsConfig(BaseModel):
    is_enabled: bool = True
    count: int = 3

class VoiceTTSConfig(BaseModel):
    is_enabled: bool = False
    voice_name: str = "zh-CN-XiaoxiaoNeural"
    speed: float = 1.0

class VoiceSTTConfig(BaseModel):
    is_enabled: bool = False
    engine: str = "openai-compatible"

class ModelItem(BaseModel):
    id: str
    name: str
    type: Optional[str] = "llm"  # "llm" (对话模型) 或 "embedding" (向量嵌入模型)
    provider: Optional[str] = "通用供应商"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    description: Optional[str] = None
    credential_model_id: Optional[str] = None  # Existing saved key to reuse when changing model ID.
    context_window: Optional[int] = Field(default=None, ge=8192)
    max_input_tokens: Optional[int] = Field(default=None, ge=1024)
    max_output_tokens: Optional[int] = Field(default=None, ge=256)

class ProviderRequest(BaseModel):
    base_url: str
    api_key: Optional[str] = None
    credential_model_id: Optional[str] = None

class ModelSettingConfig(BaseModel):
    is_enabled: bool = True
    default_model: str = ""
    default_embedding_model: Optional[str] = None
    temperature: float = 0.7
    available_models: List[ModelItem] = Field(default_factory=list)

class FrequentQuestionsConfig(BaseModel):
    is_enabled: bool = True
    threshold: int = Field(default=3, gt=0, strict=True)
    reset_required: bool = False

class AppConfigsResponse(BaseModel):
    welcome_setting: WelcomeConfig
    next_questions: NextQuestionsConfig
    voice_tts: VoiceTTSConfig
    voice_stt: VoiceSTTConfig
    model_setting: ModelSettingConfig
    frequent_questions: FrequentQuestionsConfig

class UpdateConfigPayload(BaseModel):
    is_enabled: Optional[bool] = None
    config_value: Optional[Dict[str, Any]] = None
