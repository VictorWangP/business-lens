"""One explicit tokenizer for chunking and model budgets."""
from functools import lru_cache
import tiktoken

@lru_cache(maxsize=1)
def encoding():
    return tiktoken.get_encoding('cl100k_base')


def count_message_tokens(messages):
    """Count provider-visible content, excluding LangChain tool artifacts."""
    import json
    from langchain_core.messages import convert_to_openai_messages
    wire = convert_to_openai_messages(messages)
    return len(encoding().encode(json.dumps(wire, ensure_ascii=False))) + 3 * len(messages)
