"""Provider-independent request guard; summary policy stays in framework middleware."""
import json
from langchain_core.callbacks import BaseCallbackHandler
from app.infrastructure.tokenization import encoding, count_message_tokens

class TokenBudget(BaseCallbackHandler):
    raise_error = True

    def __init__(self, total: int, context: int, output: int = 4096):
        self.total, self.context, self.output = total, context, output
        self.spent, self.input_tokens = 0, 0

    def on_chat_model_start(self, serialized, messages, **kwargs):
        schemas = json.dumps(kwargs.get('invocation_params', {}).get('tools', []), ensure_ascii=False)
        self.input_tokens = sum(count_message_tokens(group) for group in messages) + len(encoding().encode(schemas))
        if self.input_tokens + self.output > self.context or self.spent + self.input_tokens + self.output > self.total:
            raise RuntimeError('模型输入或累计 token 预算不足，请缩小问题范围')

    def on_llm_end(self, response, **kwargs):
        messages = [generation.message for group in response.generations for generation in group if hasattr(generation, 'message')]
        usage = sum((message.usage_metadata or {}).get('total_tokens', 0) for message in messages)
        self.spent += usage or self.input_tokens + len(encoding().encode(json.dumps([message.model_dump(mode='json') for message in messages], ensure_ascii=False)))
        if self.spent > self.total:
            raise RuntimeError('已达到累计 token 预算')
