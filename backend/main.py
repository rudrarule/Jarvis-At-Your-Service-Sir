from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from services import handle_chat

app = FastAPI(
    title="Holo Core Nexus API",
    description="Backend API for the J.A.R.V.I.S holographic AI assistant",
    version="0.1.0",
)

# CORS — allow the Vite dev server to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.get("/")
async def root():
    return {"status": "online", "system": "J.A.R.V.I.S", "version": "0.1.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "modules": {"neural_net": True, "voice": False, "automation": False}}


@app.post("/chat")
async def chat(request: ChatRequest):
    reply = await handle_chat(request.message)
    return {"reply": reply}
