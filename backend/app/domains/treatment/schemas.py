"""Contract for looking up the next step of a classified waste case."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CatalogKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,100}$")]
RecyclingCode = Annotated[str, Field(pattern=r"^R-(?:[1-9]|1[01])(?:-[1-9][0-9]?)?$")]
SearchRegion = Literal[
    "capital", "chungcheong", "honam", "southeast", "daegyeong", "gangwon", "jeju"
]


class RecyclingTypes(BaseModel):
    free: list[RecyclingCode] = Field(default_factory=list, max_length=50)
    analysis: list[RecyclingCode] = Field(default_factory=list, max_length=50)
    unmarked: list[RecyclingCode] = Field(default_factory=list, max_length=50)


class RecyclingBasis(BaseModel):
    version: str = Field(max_length=120)
    as_of: str = Field(max_length=10)
    source_url: str = Field(pattern=r"^https://www\.law\.go\.kr/", max_length=1500)
    pages: list[int] = Field(max_length=30)
    notes: list[str] = Field(max_length=10)


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ObservedOutput(BaseModel):
    state_key: CatalogKey | None
    mass_kg: float | None = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    purity_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    review_reference: str | None = Field(default=None, max_length=160)


class NextStepRequest(BaseModel):
    waste_code: str = Field(pattern=r"^\d{2}-\d{2}-\d{2}$")
    material: str | None = Field(default=None, max_length=80)
    input_form: str | None = Field(default=None, max_length=80)
    completed_transitions: list[CatalogKey] = Field(default_factory=list, max_length=8)
    origin: Coordinates | None = None
    observed_output: ObservedOutput | None = None
    recycling_types: RecyclingTypes | None = None
    recycling_basis: RecyclingBasis | None = None
    preview_transition: CatalogKey | None = None
    classification_session_id: UUID | None = None

    @model_validator(mode="after")
    def validate_observation(self):
        if self.observed_output is not None and not self.completed_transitions:
            raise ValueError("An observed output requires a completed transition")
        return self


class StateLabel(BaseModel):
    key: str
    label: str


class SourceLink(BaseModel):
    publisher: str
    url: str
    locator: str


class IntakeReview(BaseModel):
    form_evidence: Literal["site_example", "form_not_documented", "site_process_unconfirmed"]
    next_check: str
    sources: list[SourceLink]
    input_form: str | None = None


class HandoffVerification(BaseModel):
    process: Literal["public_evidence", "unverified"]
    intake_form: Literal["public_example", "unverified"]
    intake_specification: Literal["unverified"] = "unverified"
    current_permit: Literal["unverified"] = "unverified"
    lot_acceptance: Literal["unverified"] = "unverified"
    dispatch_status: Literal["held"] = "held"
    simulation_available: bool = False


class NextFacility(BaseModel):
    capability_key: str
    facility_key: str
    label: str
    region: str
    address: str | None = None
    evidence_basis: Literal["published_site_process", "site_role_hypothesis"]
    checks: list[str]
    sources: list[SourceLink]
    location: Coordinates | None = None
    location_source_url: str | None = None
    straight_line_distance_km: float | None = None
    road_distance_km: float | None = None
    road_duration_seconds: float | None = None
    road_distance_status: Literal[
        "not_requested", "not_configured", "missing_location", "available", "unavailable"
    ] = "not_requested"
    road_distance_provider: Literal["kakao", "osrm"] | None = None
    road_distance_checked_at: str | None = None
    distance_rank: int | None = None
    intake_review: IntakeReview | None = None
    handoff_verification: HandoffVerification | None = None


class NextProcess(BaseModel):
    transition_key: str
    label: str
    input_state: StateLabel
    output_state: StateLabel
    operation_steps: list[str]
    checks: list[str]
    facilities: list[NextFacility]
    sources: list[SourceLink]
    recycling_types: RecyclingTypes | None = None
    web_search_form: str | None = None


class PreviewStep(BaseModel):
    transition_key: str
    label: str


class NextStepResponse(BaseModel):
    status: Literal[
        "needs_input", "unsupported", "candidates", "end_of_route", "no_route", "review_required"
    ]
    backend: Literal["postgresql", "neo4j", "reference_demo"]
    waste_code: str
    code_label: str | None = None
    current_state: StateLabel | None = None
    can_finish: bool = False
    options: list[NextProcess] = Field(default_factory=list)
    process_previews: list[list[PreviewStep]] = Field(default_factory=list)
    process_previews_truncated: bool = False
    output_states: list[StateLabel] = Field(default_factory=list)
    basis: Literal["initial_input", "expected_output", "observed_output"] = "initial_input"
    message: str
    dispatch_approved: Literal[False] = False


class FacilitySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    transition_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,100}$")
    waste_code: str | None = Field(default=None, pattern=r"^\d{2}-\d{2}-\d{2}$")
    region: str | None = Field(default=None, min_length=1, max_length=160)
    origin_latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    origin_longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    page_size: int = Field(default=25, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    audience: Literal["internal", "external_model"] = "internal"

    @model_validator(mode="after")
    def private_constraints(self):
        if self.transition_key is None and self.waste_code is None:
            raise ValueError("A transition or waste code is required")
        if (self.origin_latitude is None) != (self.origin_longitude is None):
            raise ValueError("Both origin coordinates are required")
        if self.audience == "external_model" and (
            self.region is not None or self.origin_latitude is not None
        ):
            raise ValueError("Use internal facility search for private location constraints")
        return self


class FacilitySearchResponse(BaseModel):
    contract_version: Literal["kg-facility-search-v1"] = "kg-facility-search-v1"
    status: Literal["candidates", "reference_only", "no_candidates"]
    backend: Literal["postgresql", "neo4j"] = "neo4j"
    transition_key: str | None
    material: str | None
    reference_bindings: list[dict[str, Any]]
    registry_candidates: list[dict[str, Any]]
    web_research_leads: list[dict[str, Any]] = Field(default_factory=list)
    pagination: dict[str, Any]
    graph_trace: dict[str, Any]
    search_scope: dict[str, Any]
    limitations: list[str]
    dispatch_approved: Literal[False] = False


class FacilityWebSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transition_key: CatalogKey
    input_form: CatalogKey
    region: SearchRegion
    waste_code: str | None = Field(default=None, pattern=r"^\d{2}-\d{2}-\d{2}$")
    recycling_types: RecyclingTypes | None = None


class FacilityWebLead(BaseModel):
    site: str = Field(min_length=2, max_length=150)
    address: str | None = Field(max_length=240)
    process: str = Field(min_length=2, max_length=240)
    url: str = Field(pattern=r"^https://[A-Za-z0-9.-]+(?::443)?(?:[/?#]|$)", max_length=1500)


class FacilityWebSearchResponse(BaseModel):
    status: Literal["searched", "unavailable"]
    leads: list[FacilityWebLead] = Field(default_factory=list, max_length=5)
    dispatch_approved: Literal[False] = False
