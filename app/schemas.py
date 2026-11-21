"""Request and response schemas for the local API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Short = Field(default=None, max_length=64)


class Answers(BaseModel):
    """Questionnaire answers. Only identifiers from the questionnaire and short structured facts are accepted."""
    model_config = ConfigDict(extra="forbid")
    segment: Optional[str] = Short
    product_type: Optional[str] = Short
    audience: Optional[str] = Short
    channel: Optional[str] = Short
    topic: Optional[str] = Short
    scope: Optional[str] = Short
    part: Optional[str] = Short
    excluded: Optional[str] = Short
    evidence: Optional[str] = Short
    method: Optional[str] = Short
    reference_year: Optional[str] = Field(default=None, max_length=4)
    comparison: Optional[str] = Short
    use_date: Optional[str] = Field(default=None, max_length=10)
    on_market_before: Optional[str] = Short
    language: Optional[Literal["en", "de"]] = None
    tone: Optional[Literal["factual", "warm", "short"]] = None
    facts: dict[str, str] = Field(default_factory=dict)


class RecommendRequest(BaseModel):
    answers: Answers
    session_id: Optional[str] = Field(default=None, max_length=64)
    use_ai: bool = True
    save: bool = True


class RevalidateRequest(BaseModel):
    answers: Answers
    template_id: str = Field(max_length=32)
    values: dict[str, str] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    ticket_id: Optional[int] = None
    template_id: str = Field(max_length=32)
    fits: Optional[Literal["yes", "no", "unsure"]] = None
    would_use: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)


class UsabilityRequest(BaseModel):
    session_id: str = Field(max_length=64)
    ticket_id: Optional[int] = None
    question_times: dict[str, int] = Field(default_factory=dict)
    back_steps: int = 0
    time_to_first_copy_ms: Optional[int] = None


class SusRequest(BaseModel):
    session_id: str = Field(max_length=64)
    answers: list[int] = Field(min_length=10, max_length=10)


class EventRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=64)
    ticket_id: Optional[int] = None
    type: Literal["copy", "tone", "language", "sources", "duplicate", "new_ticket", "ai_adjust"]
    payload: dict = Field(default_factory=dict)


class SettingsUpdate(BaseModel):
    ollama_enabled: Optional[bool] = None
    chat_model: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._:/-]+$")
    review_mode: Optional[bool] = None
    usability_mode: Optional[bool] = None
    ai_source: Optional[Literal["local", "cloud"]] = None
    cloud_model: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._:/-]+$")
    api_key: Optional[str] = Field(default=None, max_length=200)  # write-only; "" removes the stored key


class ClearRequest(BaseModel):
    confirm: Literal["DELETE"]
