"""Durable scheduling and first-chunk argument preservation for AG-UI."""
from ag_ui_langgraph import LangGraphAgent
from ag_ui.core import ToolCallArgsEvent

class DurableLangGraphAgent(LangGraphAgent):
    recover: bool = False
    last_error: Exception | None = None

    async def _handle_stream_events(self, input):
        # LangGraphAgent.run converts exceptions into RUN_ERROR strings. Retain
        # the original privately so the application can classify safe failures.
        try:
            async for event in super()._handle_stream_events(input):
                yield event
        except Exception as exc:
            self.last_error = exc
            raise

    async def prepare_stream(self, input, agent_state, config):
        # A crashed worker resumes the next durable graph task with input=None.
        # Passing the old user input again would start a second graph invocation.
        if self.recover and agent_state.next and not any(task.interrupts for task in agent_state.tasks):
            self.active_run['schema_keys'] = self.get_schema_keys(config)
            return {'stream': self.graph.astream_events(input=None, config=config, version='v2'),
                    'state': agent_state.values, 'config': config}
        return await super().prepare_stream(input, agent_state, config)

    async def _handle_single_event(self, event, state):
        # The official adapter opens a call from the first chunk but drops any
        # arguments carried in that same chunk. Preserve them before subsequent
        # deltas arrive, including providers that send all arguments at once.
        async for item in super()._handle_single_event(event, state):
            yield item
            if (event.get('event') == 'on_chat_model_stream'
                    and item is not None and item.type == 'TOOL_CALL_START'):
                chunk = (event.get('data') or {}).get('chunk')
                chunks = chunk.get('tool_call_chunks', []) if isinstance(chunk, dict) else getattr(chunk, 'tool_call_chunks', [])
                if chunks and chunks[0].get('args'):
                    yield ToolCallArgsEvent(tool_call_id=item.tool_call_id, delta=chunks[0]['args'])
