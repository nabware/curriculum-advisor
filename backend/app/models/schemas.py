from pydantic import BaseModel, Field


class BlockedTimeWindow(BaseModel):
    day: str = Field(..., description="Day of the week, e.g. 'Monday'")
    start: str = Field(..., description="Start time, e.g. '9:00AM'")
    end: str = Field(..., description="End time, e.g. '11:00AM'")


class AdvisorRequest(BaseModel):
    major: str = Field(..., description="Student major")
    completed_courses: list[str] = Field(default_factory=list)
    preferences_text: str | None = Field(
        default=None,
        description="Free-form preferences such as 'include an operating systems class' or 'avoid difficult teachers'",
    )
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
    objective_progress_weight: float | None = Field(
        default=None,
        description="Optional weight for progress objective component",
    )
    objective_workload_weight: float | None = Field(
        default=None,
        description="Optional weight for workload objective component",
    )
    objective_sentiment_weight: float | None = Field(
        default=None,
        description="Optional weight for sentiment objective component",
    )
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
    professor_sentiment_score: float | None = None
    professor_review_summary: str | None = None
    rmp_top_tag: str | None = None
    rmp_top_tag_count: int | None = None
    rmp_top_tag_tone: str | None = None
    # RMP fields
    rmp_rating: float | None = None
    rmp_difficulty: float | None = None
    rmp_would_take_again_pct: float | None = None
    rmp_url: str | None = None
    rmp_num_ratings: int | None = None
    # Prerequisite metadata (from deterministic DAG validator)
    prerequisite_text: str | None = None
    prerequisite_satisfied_by: list[str] = Field(default_factory=list)
    rationale: str | None = None


class BlockedCourseExplanation(BaseModel):
    course_code: str
    title: str | None = None
    group_name: str | None = None
    unmet_prerequisites: str
    raw_prerequisite_text: str | None = None


class ProfessorRatingLookupResponse(BaseModel):
    professor_name: str
    rating: float | None = None
    difficulty: float | None = None
    num_ratings: int | None = None
    would_take_again_pct: float | None = None
    rmp_url: str | None = None
    top_tag: str | None = None
    top_tag_count: int | None = None
    top_tag_tone: str | None = None


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
    prerequisite_blocked_courses: list[BlockedCourseExplanation] = Field(default_factory=list)
    prerequisite_violation_count: int = 0


class ChatTurn(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str


class ChatState(BaseModel):
    major: str | None = None
    term: str | None = None
    completed_courses: list[str] = Field(default_factory=list)
    transcript_text: str | None = None
    preferences_text: str | None = None
    prefer_high_rated_professors: bool = False
    prefer_light_workload: bool = False
    max_units_per_semester: int | None = None
    blocked_time_windows: list[BlockedTimeWindow] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(..., description="The student's latest chat message")
    state: ChatState = Field(default_factory=ChatState)
    history: list[ChatTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str = Field(..., description="The assistant's natural-language reply")
    intent: str = Field(default="recommend")
    state: ChatState
    advisor: AdvisorResponse | None = None
    rationale_source: str = Field(
        default="none",
        description="One of: 'llm', 'template', 'none' — which path produced the per-course rationales",
    )
    intent_source: str = Field(
        default="fallback",
        description="One of: 'llm', 'fallback' — which path extracted the intent",
    )
    missing_required_fields: list[str] = Field(default_factory=list)
