"""Request guards and content-free diagnostics shared by agent and summary calls."""
import json
import hashlib
import logging
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import convert_to_openai_messages
from app.infrastructure.tokenization import encoding, count_message_tokens

logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class TokenBudget(BaseCallbackHandler):
    raise_error = True

    def __init__(self, total: int, context: int, output: int = 4096, *, run_id='', input_limit=None, model_key=''):
        self.total, self.context, self.output = total, context, output
        self.input_limit = input_limit or context - output
        self.model_key = model_key
        self.run_id = run_id
        self.spent, self.input_tokens = 0, 0
        self.requests = {}
        self.last_error = None
        self.accounted_message_ids = set()
        self.phase = 'agent'
        self.measurement = {}
        self.cached_tokens = 0

    @staticmethod
    def fingerprints(messages):
        return [hashlib.sha256(json.dumps(message, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                for message in convert_to_openai_messages(messages)]

    def estimate_input(self, messages, schema_tokens, *, schema_key=''):
        """Use measured prefix usage plus a local estimate of only the new suffix."""
        anchor = self.measurement
        prefix = anchor.get('prefix', [])
        if (prefix and anchor.get('model') == self.model_key and anchor.get('schema') == schema_key
                and len(messages) >= len(prefix) and self.fingerprints(messages[:len(prefix)]) == prefix):
            tail = messages[len(prefix):]
            return anchor['tokens'] + (count_message_tokens(tail) if tail else 0)
        return count_message_tokens(messages) + schema_tokens

    def fail(self, code, message):
        self.last_error = BudgetExceeded(code, message)
        logger.warning('agent_budget_exceeded run=%s code=%s spent=%d input=%d context=%d total=%d',
                       self.run_id, code, self.spent, self.input_tokens, self.context, self.total)
        raise self.last_error

    def on_chat_model_start(self, serialized, messages, **kwargs):
        params = kwargs.get('invocation_params', {})
        schemas = json.dumps(params.get('tools', []), ensure_ascii=False, sort_keys=True)
        schema_tokens = len(encoding().encode(schemas))
        schema_key = hashlib.sha256(schemas.encode()).hexdigest()
        message_tokens = sum(count_message_tokens(group) for group in messages)
        self.input_tokens = sum(self.estimate_input(group, schema_tokens, schema_key=schema_key) for group in messages)
        reserve = params.get('max_completion_tokens') or params.get('max_tokens') or self.output
        self.requests[kwargs.get('run_id')] = (self.input_tokens, reserve, messages, schema_key, self.phase)
        logger.info('agent_budget_start run=%s model_call=%s phase=%s message_tokens=%d schema_tokens=%d '
                    'input_estimated=%d output_reserved=%d spent=%d context_limit=%d total_limit=%d',
                    self.run_id, kwargs.get('run_id'), self.phase, message_tokens, schema_tokens,
                    self.input_tokens, reserve, self.spent, self.context, self.total)
        if self.input_tokens > self.input_limit or self.input_tokens + reserve > self.context:
            self.fail('CONTEXT_TOKEN_LIMIT', '本次模型输入超过上下文预算，压缩后仍无法容纳，请缩小问题或资料范围。')
        if self.total and self.spent + self.input_tokens + reserve > self.total:
            self.fail('TOTAL_TOKEN_LIMIT', '本轮累计 token 预算不足，请缩小分析范围或调整累计执行预算。')

    def on_llm_end(self, response, **kwargs):
        input_tokens, _, sent, schema_key, phase = self.requests.pop(
            kwargs.get('run_id'), (self.input_tokens, self.output, [], '', self.phase))
        messages = [generation.message for group in response.generations for generation in group if hasattr(generation, 'message')]
        usage = sum((message.usage_metadata or {}).get('total_tokens', 0) for message in messages)
        consumed = usage or input_tokens + sum(count_message_tokens([message]) for message in messages)
        self.spent += consumed
        cached = sum((message.usage_metadata or {}).get('input_token_details', {}).get('cache_read', 0) or 0
                     for message in messages)
        self.cached_tokens += cached
        if phase == 'agent' and len(sent) == len(messages) == 1:
            usage_data = messages[0].usage_metadata or {}
            if usage_data.get('input_tokens'):
                self.measurement = {'model': self.model_key, 'schema': schema_key,
                    'prefix': self.fingerprints([*sent[0], messages[0]]),
                    'tokens': usage_data['input_tokens'] + usage_data.get('output_tokens', 0)}
        self.accounted_message_ids.update(message.id for message in messages if message.id)
        logger.info('agent_budget_end run=%s model_call=%s phase=%s usage_source=%s consumed=%d spent=%d '
                    'cached_tokens=%d total_limit=%d', self.run_id, kwargs.get('run_id'), phase,
                    'provider' if usage else 'estimated', consumed, self.spent, cached, self.total)
        if self.total and self.spent > self.total:
            self.fail('TOTAL_TOKEN_LIMIT', '本轮已达到累计 token 预算，请缩小分析范围或调整累计执行预算。')

    def on_llm_error(self, error, **kwargs):
        self.requests.pop(kwargs.get('run_id'), None)
