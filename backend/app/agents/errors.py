"""Safe execution-limit errors crossing the official streaming adapter boundary."""
from langgraph.errors import GraphRecursionError
from langchain_core.exceptions import ContextOverflowError


class ExecutionLimitExceeded(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def is_context_overflow(error):
    if isinstance(error, ContextOverflowError):
        return True
    if getattr(error, 'code', None) == 'CONTEXT_TOKEN_LIMIT':
        return True
    body = getattr(error, 'body', None)
    detail = body.get('error', body) if isinstance(body, dict) else {}
    if not isinstance(detail, dict):
        detail = {}
    code = getattr(error, 'code', None) or detail.get('code')
    return code in {'context_length_exceeded', 'max_input_length_exceeded', 'input_length_exceeded',
                    'context_window_exceeded'}


def classify_execution_error(error):
    if isinstance(error, GraphRecursionError):
        return ExecutionLimitExceeded('GRAPH_STEP_LIMIT', '本轮图执行步数达到保护上限，任务尚未完成，请缩小分析范围或检查执行循环。')
    return error


def graph_recursion_limit(graph, model_calls):
    # A graph step is not a model call: every before/after middleware hook is
    # another node. Use the actual graph size as a conservative per-call bound,
    # plus one cycle for limit detection and room for start/end nodes.
    nodes = max(1, len(graph.get_graph().nodes) - 2)
    return nodes * (model_calls + 1) + 2
