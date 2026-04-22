"""
chat_model.py — Pydantic Models for API Requests/Responses
"""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str


class TTSRequest(BaseModel):
    text: str
