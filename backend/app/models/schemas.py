from pydantic import BaseModel, Field


class AdvisorRequest(BaseModel):
    major: str = Field(..., description="Student major")
    completed_courses: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    career_goals: list[str] = Field(default_factory=list)
    prefer_light_workload: bool = False
    prefer_high_rated_professors: bool = False
    max_units_per_semester: int = Field(
        default=12, description="Maximum units willing to take this semester"
    )
    term: str | None = Field(
        default=None, description="Term to filter course availability (e.g., 'Spring 2026')"
    )


class RecommendedCourse(BaseModel):
    course_code: str
    title: str
    group_name: str | None = None
    units: int | None = None
    offered_terms: list[str] = Field(default_factory=list)
    days_times: str | None = None
    instructor: str | None = None
    description: str | None = None
    professor_name: str | None = None
    professor_image_url: str | None = None


class RequirementGroupRecommendation(BaseModel):
    group_name: str
    min_units: int | None = None
    max_units: int | None = None
    courses: list[RecommendedCourse] = Field(default_factory=list)


class DegreeProgram(BaseModel):
    id: int
    degree_name: str


class DegreeProgramsResponse(BaseModel):
    degrees: list[DegreeProgram]


class AdvisorResponse(BaseModel):
    grouped_recommendations: list[RequirementGroupRecommendation] = Field(default_factory=list)
    recommendations: list[RecommendedCourse]
    explanation: str
    total_units_selected: int = 0
    total_units_required: int = 0
