from pydantic import BaseModel, Field


class AdvisorRequest(BaseModel):
    major: str = Field(..., description="Student major")
    completed_courses: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    career_goals: list[str] = Field(default_factory=list)
    prefer_light_workload: bool = False
    prefer_high_rated_professors: bool = False


class RecommendedCourse(BaseModel):
    course_code: str
    title: str
    reason: str


class AdvisorResponse(BaseModel):
    recommendations: list[RecommendedCourse]
    explanation: str
