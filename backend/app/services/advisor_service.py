from app.models.schemas import AdvisorRequest, AdvisorResponse, RecommendedCourse


class AdvisorService:
    @staticmethod
    def recommend(payload: AdvisorRequest) -> AdvisorResponse:
        # Minimal placeholder ranking logic for initial integration.
        sample = [
            RecommendedCourse(
                course_code="CSC 6XX",
                title="Sample Elective",
                reason="Matches interests and keeps progress on track.",
            )
        ]
        return AdvisorResponse(
            recommendations=sample,
            explanation=(
                "This is a starter response. Replace with prerequisite checks, "
                "sentiment scoring, and ranking logic."
            ),
        )
