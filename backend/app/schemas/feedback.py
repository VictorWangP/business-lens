from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.agents.answer import BusinessPresentation

FeedbackStatus = Literal['pending', 'resolved']
FeedbackReason = Literal['data_error', 'irrelevant', 'citation_error', 'presentation_error', 'other']


class FeedbackSnapshotV2(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[2]
    answer: dict
    presentation: BusinessPresentation
    context: dict
    resource: dict
    execution: dict
    completeness: dict


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: FeedbackReason
    comment: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_comment(self):
        if self.reason == 'other' and not self.comment:
            raise ValueError('选择其他原因时请填写补充说明')
        return self


class FeedbackUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    status: FeedbackStatus
    processing_note: str = Field(max_length=4000)
    expected_version: int = Field(ge=1)

    @model_validator(mode='after')
    def validate_note(self):
        if self.status == 'resolved' and not self.processing_note:
            raise ValueError('标记已处理时必须填写处理备注')
        return self
