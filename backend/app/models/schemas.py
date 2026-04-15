from pydantic import BaseModel, Field


class BlockedTimeWindow(BaseModel):
    day: str = Field(..., description="Day of the week, e.g. 'Monday'")
    start: str = Field(..., description="Start time, e.g. '9:00AM'")
    end: str = Field(..., description="End time, e.g. '11:00AM'")


class AdvisorRequest(BaseModel):
    major: str = Field(..., description="Student major")
    completed_courses: list[str] = Field(default_factory=list)
    transcript_text: str | None = Field(
        default=None, description="Raw transcript text; course codes are parsed automatically"
    )
    blocked_time_windows: list[BlockedTimeWindow] = Field(
        default_factory=list,
        description="Day/time ranges when the student is unavailable",
    )
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
    # RMP fields
    rmp_rating: float | None = None
    rmp_difficulty: float | None = None
    rmp_would_take_again_pct: float | None = None
    rmp_url: str | None = None
    rmp_num_ratings: int | None = None


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
