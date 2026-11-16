"""Validate curated treatment reference data stored by SCRAP."""

import json
import unicodedata
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ASSETS = Path(__file__).with_name("resources")
MATERIAL_ALIASES = {
    "pet": ["pet", "페트", "polyethylene terephthalate", "폴리에틸렌테레프탈레이트"],
    "aluminium": ["aluminium", "aluminum", "알루미늄"],
    "paper": ["paper", "종이", "종이류", "폐지"],
    "pp": ["pp", "polypropylene", "폴리프로필렌"],
    "pe": ["pe", "polyethylene", "폴리에틸렌", "hdpe", "ldpe", "lldpe"],
    "abs": ["abs", "아크릴로니트릴부타디엔스티렌"],
    "ps": ["ps", "polystyrene", "폴리스티렌", "hips", "gpps"],
    "san": ["san", "as", "styrene acrylonitrile"],
    "pvc": ["pvc", "polyvinyl chloride", "폴리염화비닐", "염화비닐"],
    "eps": ["eps", "expanded polystyrene", "발포폴리스티렌", "스티로폼"],
    "pa6": ["pa6", "pa 6", "nylon 6", "나일론6"],
    "pa66": ["pa66", "pa 66", "nylon 66", "나일론66"],
    "pcabs": ["pc/abs", "pc-abs", "pc abs", "pcabs"],
    "ferrous": ["ferrous", "ferrous_scrap", "철스크랩", "철 스크랩", "고철"],
}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def normalize_label(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def identity(kind, value):
    return kind + ":" + digest(value)[:32]


def read_bundle(name):
    return json.loads((ASSETS / name).read_text(encoding="utf8"))


def resolve_material(value):
    if value is None:
        return None
    normalized = normalize_label(value)
    if normalized.replace(" ", "") in {
        "hdpe",
        "ldpe",
        "lldpe",
        "mdpe",
        "uhmwpe",
        "고밀도폴리에틸렌",
        "저밀도폴리에틸렌",
        "선형저밀도폴리에틸렌",
    }:
        return "pe"
    return next(
        (
            key
            for key, aliases in MATERIAL_ALIASES.items()
            if normalized in {normalize_label(label) for label in (key, *aliases)}
        ),
        None,
    )


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9-]{0,100}$")


SupportGroup = Literal["states", "transitions", "organisations", "facilities", "capabilities"]
SupportKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,100}$")]
SupportTargets = Annotated[list[SupportKey], Field(min_length=1)]


class SourceRecord(Record):
    """Curator-declared linkage scope, not an audit of the source's contents."""

    # Citation metadata only; this field never triggers an HTTP fetch.
    url: str = Field(pattern=r"^https?://")
    publisher: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    checked_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_date: str | None
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    acquisition: str
    digest_basis: Literal["downloaded-original-bytes", "curator-record-not-original-page"]
    model_transfer_allowed: bool
    export_scope: Literal["team-authored-factual-summary-only; raw-page-and-assets-excluded"]
    supported_records: dict[SupportGroup, SupportTargets] = Field(
        min_length=1,
        description="Curator-declared support, pending independent verification",
    )

    @model_validator(mode="after")
    def unique_support_targets(self):
        date.fromisoformat(self.checked_date)
        if self.source_date is not None:
            date.fromisoformat(self.source_date)
        if any(len(keys) != len(set(keys)) for keys in self.supported_records.values()):
            raise ValueError("Duplicate source support target")
        return self


class SourcedRecord(Record):
    label: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)


class MaterialState(SourcedRecord):
    material: str
    input_forms: list[str]
    is_entry: bool
    is_output: bool


class ProcessTransition(SourcedRecord):
    input_state: str
    output_state: str
    operation_steps: list[str] = Field(min_length=1)
    conditions: list[str] = Field(min_length=1)
    risk_checks: list[str] = Field(min_length=1)


class Organisation(SourcedRecord):
    pass


class ReportedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: float = Field(gt=0, allow_inf_nan=False)
    unit: str
    scope: Literal["website-reported-design-capacity-not-current-available"]
    source_id: str


class Facility(SourcedRecord):
    organisation: str
    country: Literal["KR"]
    region: str
    address: str | None
    reported_metrics: list[ReportedMetric]
    # Reference cases cannot set current permit, available capacity, price or acceptance.
    current_permit_scope: None
    current_available_capacity_kg: None
    current_acceptance: None
    current_price_krw_per_kg: None
    latitude: float | None = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(ge=-180, le=180, allow_inf_nan=False)


class FacilityInputProfile(BaseModel):
    """Public examples are open lists, not exclusive intake specifications."""

    model_config = ConfigDict(extra="forbid")
    evidence_scope: Literal["site_publication", "organisation_only_not_site_verified"]
    material_examples: list[str]
    form_examples: list[str]
    output_description: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    locator: str = Field(min_length=1)
    excludes_designated_waste: Literal[True] | None = None
    exclusion_source_ids: list[str] = Field(default_factory=list)
    exclusion_locator: str | None = None
    verified_intake_limits_available: Literal[False] = False

    @model_validator(mode="after")
    def scope_is_explicit(self):
        excluded = self.excludes_designated_waste is True
        if excluded != bool(self.exclusion_source_ids) or excluded != bool(self.exclusion_locator):
            raise ValueError("Explicit exclusion needs its own source and locator")
        if excluded and self.evidence_scope != "site_publication":
            raise ValueError("Organisation hypothesis cannot assert a site exclusion")
        return self


class Capability(Record):
    facility: str
    transition: str
    basis: Literal["published_site_process", "site_role_hypothesis"]
    source_ids: list[str] = Field(min_length=1)
    conditions: list[str] = Field(min_length=1)
    input_profile: FacilityInputProfile
    initial_input_forms: list[str] | None = Field(default=None, min_length=1)


class PlanningReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["planning-reference-v2"]
    scope: str
    sources: list[SourceRecord]
    states: list[MaterialState]
    transitions: list[ProcessTransition]
    organisations: list[Organisation]
    facilities: list[Facility]
    capabilities: list[Capability]

    @model_validator(mode="after")
    def check_references(self):
        mappings = {}
        for name in GROUPS:
            rows = getattr(self, name)
            mappings[name] = {r.key: r for r in rows}
            if len(mappings[name]) != len(rows):
                raise ValueError("Duplicate planning reference key")
        sources, states = mappings["sources"], mappings["states"]
        for source in self.sources:
            for group, keys in source.supported_records.items():
                if not set(keys) <= mappings[group].keys():
                    raise ValueError("Unlinked source support target")
        for name in GROUPS:
            if name == "sources":
                continue
            for row in getattr(self, name):
                if (
                    len(set(row.source_ids)) != len(row.source_ids)
                    or not set(row.source_ids) <= sources.keys()
                ):
                    raise ValueError("Unlinked planning source")
                if any(
                    row.key not in sources[sid].supported_records.get(name, [])
                    for sid in row.source_ids
                ):
                    raise ValueError("Planning source outside declared support scope")
        for state in self.states:
            if state.material not in MATERIAL_ALIASES:
                raise ValueError("Unknown planning material")
        for transition in self.transitions:
            if transition.input_state not in states or transition.output_state not in states:
                raise ValueError("Unlinked material state")
            if (
                transition.input_state == transition.output_state
                or states[transition.input_state].material
                != states[transition.output_state].material
            ):
                raise ValueError("Invalid or cross-material transition")
        for facility in self.facilities:
            if facility.organisation not in mappings["organisations"]:
                raise ValueError("Unlinked organisation")
            if any(m.source_id not in facility.source_ids for m in facility.reported_metrics):
                raise ValueError("Unlinked reported metric")
            if (facility.latitude is None) != (facility.longitude is None):
                raise ValueError("Incomplete location point")
        for capability in self.capabilities:
            if (
                capability.facility not in mappings["facilities"]
                or capability.transition not in mappings["transitions"]
            ):
                raise ValueError("Unlinked facility capability")
            profile = capability.input_profile
            input_state = states[mappings["transitions"][capability.transition].input_state]
            if (
                not set(profile.source_ids + profile.exclusion_source_ids)
                <= set(capability.source_ids)
                or any(m not in MATERIAL_ALIASES for m in profile.material_examples)
                or input_state.material not in profile.material_examples
                or (
                    capability.initial_input_forms is not None
                    and (
                        not set(capability.initial_input_forms) <= set(input_state.input_forms)
                        or not set(capability.initial_input_forms) <= set(profile.form_examples)
                    )
                )
                or (profile.evidence_scope == "site_publication")
                != (capability.basis == "published_site_process")
            ):
                raise ValueError("Invalid or unlinked facility input profile")
        return self


GROUPS = {
    "sources": "Source",
    "states": "MaterialState",
    "transitions": "ProcessTransition",
    "organisations": "Organisation",
    "facilities": "Facility",
    "capabilities": "FacilityCapability",
}


def node_id(kind, key):
    return identity("planning-" + kind, key)
