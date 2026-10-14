"""Only provider boundaries are substituted; orchestration/checkpoints stay real."""
import json
import uuid
from typing import Any
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

CFG = {'model_id':'test','base_url':'http://test/v1','api_key':'test','temperature':0}
QUESTIONS=['查看明细？','比较业务差异？','进一步解释口径？']

def chat_input(query='', workspace_id=None, conversation_id=None, **props):
    return {'threadId':conversation_id or str(uuid.uuid4()),'runId':str(uuid.uuid4()),
        'messages':[{'id':str(uuid.uuid4()),'role':'user','content':query}],
        'tools':[],'context':[],'state':{},'forwardedProps':{'workspace_id':workspace_id,**props}}

def answer(text='当前数据不足以确认增长。', enabled=True):
    return {'version':1,'sections':[{'title':'业务分析','summary':text}], 'suggestions':QUESTIONS if enabled else []}

class ScriptedModel(BaseChatModel):
    respond: Any
    final_tool: str = 'SuggestedAnswer'
    @property
    def _llm_type(self): return 'offline-provider-substitute'
    def bind_tools(self, tools, **kwargs):
        for tool in tools:
            if isinstance(tool,dict):
                name=tool.get('name') or tool.get('function',{}).get('name')
                if name in {'SuggestedAnswer','PlainAnswer'}: self.final_tool=name
            elif getattr(tool,'name',None) in {'SuggestedAnswer','PlainAnswer'}:
                self.final_tool=tool.name
        return self
    def response(self,messages):
        result=self.respond(messages)
        if isinstance(result,dict) and 'sections' in result:
            return AIMessage(content='',tool_calls=[{'id':str(uuid.uuid4()),'name':self.final_tool,'args':result}])
        return result
    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.response(messages))])
    def _stream(self,messages,stop=None,run_manager=None,**kwargs):
        message=self.response(messages)
        if message.content:
            yield ChatGenerationChunk(message=AIMessageChunk(content=message.content))
        for index,call in enumerate(message.tool_calls):
            yield ChatGenerationChunk(message=AIMessageChunk(content='',tool_call_chunks=[{
                'name':call['name'],'id':call['id'],'args':json.dumps(call['args'],ensure_ascii=False),'index':index}]))

def install_model(monkeypatch,respond):
    model=ScriptedModel(respond=respond)
    monkeypatch.setattr('langchain_openai.ChatOpenAI',lambda **kwargs:model)
    return model

def read_events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]

def presentation(events):
    return next(event['content'] for event in reversed(events) if event['type']=='ACTIVITY_SNAPSHOT')
