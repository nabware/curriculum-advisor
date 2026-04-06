from fastapi import APIRouter

from app.models.schemas import AdvisorRequest, AdvisorResponse, DegreeProgramsResponse
from app.services.advisor_service import AdvisorService

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.post("/recommend", response_model=AdvisorResponse)
def recommend_courses(payload: AdvisorRequest) -> AdvisorResponse:
    return AdvisorService.recommend(payload)


@router.get("/degrees", response_model=DegreeProgramsResponse)
def list_degrees() -> DegreeProgramsResponse:
    return AdvisorService.list_degrees()
