"""Resolve provider capacity separately from application execution policy."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit
from app.config import settings


@dataclass(frozen=True)
class ModelLimits:
    context: int
    input: int
    output: int
    source: str


def resolve_model_limits(config: dict) -> ModelLimits:
    host = (urlsplit(config.get('base_url', '')).hostname or '').lower()
    official = host.endswith('.maas.aliyuncs.com') or host in {
        'dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com'}
    # Only verified commercial families on official endpoints. A matching name on
    # an arbitrary proxy does not establish that deployment's actual capacity.
    qwen = official and bool(re.fullmatch(
        r'qwen3\.(?:7-(?:max|plus|flash)|8-(?:max|flash))(?:-(?:\d{4}-\d{2}-\d{2}|\d{4}))?',
        config.get('model_id', '')))
    context = config.get('context_window') or (1_000_000 if qwen else settings.AGENT_DEFAULT_CONTEXT_TOKENS)
    max_input = config.get('max_input_tokens') or (991_808 if qwen else context)
    max_output = config.get('max_output_tokens') or (131_072 if qwen else settings.AGENT_MAX_OUTPUT_TOKENS)
    if settings.AGENT_CONTEXT_TOKENS:
        context = min(context, settings.AGENT_CONTEXT_TOKENS)
    output = min(max_output, settings.AGENT_MAX_OUTPUT_TOKENS, max(1, context // 4))
    return ModelLimits(context=context, input=min(max_input, context - output), output=output,
                       source='configured' if config.get('context_window') else 'bailian' if qwen else 'fallback')
