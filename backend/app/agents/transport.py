"""One narrow scheduling extension to the official AG-UI adapter."""
from ag_ui_langgraph import LangGraphAgent

class DurableLangGraphAgent(LangGraphAgent):
    recover: bool = False

    async def prepare_stream(self, input, agent_state, config):
        # A crashed worker resumes the next durable graph task with input=None.
        # Passing the old user input again would start a second graph invocation.
        if self.recover and agent_state.next and not any(task.interrupts for task in agent_state.tasks):
            self.active_run['schema_keys'] = self.get_schema_keys(config)
            return {'stream': self.graph.astream_events(input=None, config=config, version='v2'),
                    'state': agent_state.values, 'config': config}
        return await super().prepare_stream(input, agent_state, config)
