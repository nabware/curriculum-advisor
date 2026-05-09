from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    AdvisorRequest,
    AdvisorResponse,
    ChatRequest,
    ChatResponse,
    DegreeProgramsResponse,
    ProfessorRatingLookupResponse,
)
from app.services.advisor_service import AdvisorService
from app.services.chat_service import ChatService
from app.services.rmp_service import fetch_professor_rating

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.post("/recommend", response_model=AdvisorResponse)
def recommend_courses(payload: AdvisorRequest) -> AdvisorResponse:
    return AdvisorService.recommend(payload)


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    return ChatService.respond(payload)


@router.get("/degrees", response_model=DegreeProgramsResponse)
def list_degrees() -> DegreeProgramsResponse:
    return AdvisorService.list_degrees()


@router.get("/professor-rating", response_model=ProfessorRatingLookupResponse)
def lookup_professor_rating(name: str = Query(..., min_length=1)) -> ProfessorRatingLookupResponse:
    rating = fetch_professor_rating(name)
    if not rating:
        raise HTTPException(status_code=404, detail="No professor rating found for that name")
    return ProfessorRatingLookupResponse(**rating)
