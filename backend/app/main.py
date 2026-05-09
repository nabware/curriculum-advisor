import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.advisor import router as advisor_router
from app.api.routes.health import router as health_router
from app.services.chat_service import ChatService

app = FastAPI(title="Curriculum Advisor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(advisor_router)

project_root = Path(__file__).resolve().parents[2]
professor_images_dir = project_root / "data" / "raw" / "professor_images"
if professor_images_dir.exists():
    app.mount(
        "/assets/professor-images",
        StaticFiles(directory=professor_images_dir),
        name="professor-images",
    )


@app.on_event("startup")
def _warm_up_chat_model() -> None:
    """Fire one Llama 3.2 3B intent call so the first user message isn't a cold start.

    Skipped when CURRICULUM_ADVISOR_DISABLE_CHAT_WARMUP is set (useful for tests
    or for environments where Ollama is intentionally unavailable).
    """
    if os.environ.get("CURRICULUM_ADVISOR_DISABLE_CHAT_WARMUP"):
        return
    threading.Thread(target=ChatService.warmup, name="chat-warmup", daemon=True).start()
