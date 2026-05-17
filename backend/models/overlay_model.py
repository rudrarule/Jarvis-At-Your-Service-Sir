"""Pydantic models for overlay APIs."""
from pydantic import BaseModel


class OverlayFollowUpRequest(BaseModel):
    context_id: str
    question: str
    session_id: str = "overlay"


class OverlayHistoryResponse(BaseModel):
    history: list[dict]
    count: int
