from datetime import datetime
from typing import Literal
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, field_validator, model_validator


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class Login(BaseModel):
    email: str
    password: str


class ServiceIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    environment: str = "demo"
    criticality: Literal["low", "medium", "high", "critical"] = "high"
    owner: str = Field(min_length=2)
    dependencies_json: list[str] = Field(default_factory=list)


class SourceIn(BaseModel):
    service_id: str
    name: str
    type: Literal["json", "key_value", "text"]
    parser_config: dict = Field(default_factory=dict)


class PasteIn(BaseModel):
    text: str = Field(max_length=10 * 1024 * 1024)
    service: str = "checkout-api"


class EventsIn(BaseModel):
    events: list[dict] = Field(max_length=10000)
    service: str = "checkout-api"


class RuleIn(BaseModel):
    name: str
    query_type: Literal["http", "database", "latency", "auth", "restart", "error_ratio"]
    pattern: str = ""
    threshold: float = Field(gt=0)
    window_seconds: int = Field(ge=1, le=86400)
    severity: Literal["SEV-1", "SEV-2", "SEV-3", "SEV-4"]
    enabled: bool = True

    @model_validator(mode="after")
    def threshold_policy(self):
        if self.query_type == "error_ratio" and not 0 < self.threshold < 1:
            raise ValueError("Error-ratio threshold must be between zero and one")
        if self.query_type in ("http", "database", "auth", "restart") and (
            self.threshold < 1 or not self.threshold.is_integer()
        ):
            raise ValueError("Count thresholds must be positive integers")
        return self


class EvaluateIn(BaseModel):
    service_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "revise"]
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResolutionIn(BaseModel):
    actual_action: str = Field(min_length=10)
    validation_event_ids: list[str] = Field(min_length=1)
    validation_notes: str = Field(min_length=10)
    simulated: bool = True


class StatusIn(BaseModel):
    status: Literal["INVESTIGATING", "FALSE_POSITIVE", "CLOSED"]
    reason: str = Field(min_length=5)


class SeverityIn(BaseModel):
    severity: Literal["SEV-1", "SEV-2", "SEV-3", "SEV-4"]
    reason: str = Field(min_length=5)


class KnowledgeIn(BaseModel):
    service_id: str
    title: str = Field(min_length=3)
    version: str = "1.0"
    environment: str = "demo"
    content: str = Field(min_length=30, max_length=100000)
    status: Literal["current", "outdated"] = "current"
