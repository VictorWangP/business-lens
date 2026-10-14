from llama_index.core.utils import get_tokenizer


def encoding():
    # Pinned llama-index-core bundles cl100k_base; initialize through its offline cache.
    tokenizer = get_tokenizer()
    return tokenizer.func.__self__
