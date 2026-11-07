"""Deterministic next-process lookup over the server's curated reference."""

from dataclasses import dataclass

from app.domains.treatment.classification import INITIAL_PROFILES
from app.domains.treatment.directory import load_codebook, straight_line_km
from app.domains.treatment.errors import TreatmentError
from app.domains.treatment.reference import normalize_label, resolve_material
from app.domains.treatment.schemas import NextStepRequest, NextStepResponse, RecyclingTypes

MAX_EXPANSIONS = 10000
MAX_PLANS = 2000

FORM_ALIASES = {
    "bottle": ["병", "pet병", "페트병"],
    "bale": ["압축베일", "베일"],
    "flake": ["플레이크", "플레이크형"],
    "scrap": ["스크랩", "잔재", "폐스크랩"],
    "rigid": ["경질", "경질플라스틱"],
    "film": ["필름"],
    "shredded": ["파쇄품", "파쇄물"],
    "pellet": ["펠렛", "펠릿"],
    "can": ["캔", "음료캔", "사용후음료캔", "ubc"],
    "cardboard": ["골판지", "폐골판지"],
    "recovered_paper": ["폐지", "고지"],
}


def normalize_form(value):
    if not value or value.strip().lower() in {"unknown", "미확인", "모름", "미상", "불명", "n/a"}:
        return None
    normalized = normalize_label(value)
    return next(
        (key for key, aliases in FORM_ALIASES.items() if normalized in [key, *aliases]),
        normalized,
    )


@dataclass
class Enumeration:
    paths: list
    expansions: int = 0
    budget_exhausted: bool = False
    depth_limited: bool = False


def enumerate_paths(value, material, input_form, goal_state, max_steps, *, start_state=None):
    """Deterministic bounded DFS; outputs can be intermediate states, not only sinks."""
    states = {s.key: s for s in value.states}
    adjacency, bindings = {}, {}
    for transition in sorted(value.transitions, key=lambda t: t.key):
        adjacency.setdefault(transition.input_state, []).append(transition)
    for capability in sorted(value.capabilities, key=lambda c: c.key):
        bindings.setdefault(capability.transition, []).append(capability)
    starts = sorted(
        s.key
        for s in value.states
        if s.material == material
        and (
            s.key == start_state
            if start_state is not None
            else s.is_entry and (input_form is None or input_form in s.input_forms)
        )
    )
    result = Enumeration([])

    def walk(current, path, visited):
        if result.budget_exhausted:
            return
        if path and (current == goal_state if goal_state else states[current].is_output):
            result.paths.append(tuple(path))
            if len(result.paths) >= MAX_PLANS:
                result.budget_exhausted = True
                return
            if goal_state:
                return
        following = [
            (transition, capability)
            for transition in adjacency.get(current, [])
            if transition.output_state not in visited
            for capability in bindings.get(transition.key, [None])
            if capability is None
            or capability.initial_input_forms is None
            or (not path and start_state is None and input_form in capability.initial_input_forms)
        ]
        if len(path) >= max_steps:
            result.depth_limited |= bool(following)
            return
        for transition, capability in following:
            if result.expansions >= MAX_EXPANSIONS:
                result.budget_exhausted = True
                return
            result.expansions += 1
            walk(
                transition.output_state,
                [*path, (transition, capability)],
                visited | {transition.output_state},
            )
            if result.budget_exhausted:
                return

    for start in starts:
        walk(start, [], {start})
        if result.budget_exhausted:
            break
    return result, starts


# Curated MVP entry cases. A code alone cannot resolve a resin or a lot's state.
ENTRY_FORMS = {
    "51-03-01": {
        "pp": {"scrap", "rigid", "film", "shredded", "flake", "pellet"},
        "pe": {"scrap", "rigid", "film", "shredded", "flake", "pellet"},
        "pet": {"bottle", "bale", "flake"},
    },
    "51-03-07": {
        "pp": {"scrap", "rigid", "film"},
        "pe": {"scrap", "rigid", "film"},
        "pet": {"bottle", "bale"},
    },
    "51-29-03": {"aluminium": {"can"}},
}

# Search hints for the documented outputs. A matching type still needs a site-level check.
PP_SEARCH_TYPES = {
    "pp-prepare": ("R-10",),
    "pp-clean": ("R-10",),
    "pp-pelletise": ("R-3-3", "R-10"),
    "pp-shredded-to-pellet": ("R-3-3", "R-10"),
    "pp-compound": ("R-3-3", "R-4-4", "R-10"),
}


def search_recycling_types(transition_key, types):
    keys = PP_SEARCH_TYPES.get(transition_key)
    if types is None or keys is None:
        return None
    return RecyclingTypes(
        **{
            group: list(
                dict.fromkeys(
                    code
                    for code in codes
                    if any(code == key or code.startswith(f"{key}-") for key in keys)
                )
            )
            for group, codes in types.model_dump().items()
        }
    )


def web_search_packet(request, reference):
    transition = next((t for t in reference.transitions if t.key == request.transition_key), None)
    if transition is None or transition.key not in PP_SEARCH_TYPES:
        raise TreatmentError("invalid-transition", "PP의 검수된 공정을 선택해 주세요.")
    state = next(s for s in reference.states if s.key == transition.input_state)
    forms = state.input_forms or ["washed"]
    profile = INITIAL_PROFILES.get(("pp", request.input_form))
    if request.input_form not in forms or (
        request.waste_code and (profile is None or request.waste_code not in profile.waste_codes)
    ):
        raise TreatmentError("invalid-transition", "이 공정에 맞는 PP 형태를 선택해 주세요.")
    types = search_recycling_types(
        transition.key, request.recycling_types if request.waste_code else None
    )
    sites = {facility.key: facility.label for facility in reference.facilities}
    sources = {
        source.key: source.url for source in reference.sources if source.model_transfer_allowed
    }
    starting_points = [
        {"site": sites[capability.facility], "url": sources[source_id]}
        for capability in reference.capabilities
        if capability.transition == transition.key
        and capability.basis == "published_site_process"
        and request.input_form in capability.input_profile.form_examples
        for source_id in capability.input_profile.source_ids
        if source_id in sources
    ]
    return {
        "transition_key": transition.key,
        "input_form": request.input_form,
        "region": request.region,
        "waste_code": request.waste_code,
        "recycling_types": types.model_dump() if types is not None else None,
        "starting_points": starting_points[:3],
    }


# Public map points tied to the exact facility/address. Used for approximate
# distances only. Separate from published process evidence.
MAP_POINTS = {
    "samyang-sihwa": (37.3342268, 126.7039098, "https://juso.app/b/iq03tvk7uma42oyr"),
    "jungang-gongju": (36.3190188, 127.0303035, "https://www.jungangenb.com/about/location"),
    "bgf-yesan": (
        36.7990626,
        126.695566,
        "https://findby.co.kr/details/32401-448103353161-st-686c1167f99e2ce9c5b60275",
    ),
    "novelis-yeongju": (
        36.793474,
        128.623877,
        "https://novelis.com/ko/locations/yeongju-south-korea/",
    ),
}


def next_step(request: NextStepRequest, reference_data) -> NextStepResponse:
    code = request.waste_code
    row = load_codebook()["records"].get(code)
    base = {
        "backend": "postgresql",
        "waste_code": code,
        "code_label": row["label_excerpt"] if row else None,
    }
    materials = ENTRY_FORMS.get(code)
    if not row or not materials:
        return NextStepResponse(
            **base, status="unsupported", message="이 분류번호의 검수된 공정 경로가 아직 없습니다."
        )
    material = resolve_material(request.material)
    form = normalize_form(request.input_form)
    if not request.material or not form:
        return NextStepResponse(
            **base, status="needs_input", message="문진의 재질과 현재 형태를 확인해 주세요."
        )
    if not request.completed_transitions:
        profile = INITIAL_PROFILES.get((material, form))
        if profile is None or code not in profile.waste_codes:
            return NextStepResponse(
                **base,
                status="unsupported",
                message=(
                    "새 로트의 지원 범위는 PP 사출 잔재·파쇄품, "
                    "PE 필름, PET병, 알루미늄 음료캔입니다."
                ),
            )
    if form not in materials.get(material, set()) or material not in row["query_materials"]:
        return NextStepResponse(
            **base,
            status="unsupported",
            message="이 분류번호·재질·형태 조합의 공정 근거가 없습니다.",
        )

    def project(value):
        completed = request.completed_transitions
        observed = request.observed_output
        states = {state.key: state for state in value.states if state.material == material}
        metadata = {
            **base,
            "basis": "observed_output"
            if observed
            else "expected_output"
            if completed
            else "initial_input",
            "output_states": [
                {"key": state.key, "label": state.label} for state in states.values()
            ],
        }
        current_state = None
        if observed:
            transitions = {t.key: t for t in value.transitions if t.input_state in states}
            if any(key not in transitions for key in completed):
                raise TreatmentError("invalid-progress", "완료한 공정을 확인해 주세요.")
            current_state = states.get(observed.state_key)
            if observed.state_key and current_state is None:
                raise TreatmentError("invalid-progress", "해당 재질의 산출물 상태를 확인해 주세요.")
            if observed.mass_kg == 0 or current_state is None:
                message = (
                    "이어 보낼 산출물 중량이 0 kg입니다."
                    if observed.mass_kg == 0
                    else "등록된 상태로 분류되지 않은 산출물입니다. 후속 공정을 보류합니다."
                )
                return NextStepResponse(**metadata, status="no_route", message=message)
            expected = transitions[completed[-1]].output_state
            if current_state.key != expected and not (observed.review_reference or "").strip():
                return NextStepResponse(
                    **metadata,
                    status="review_required",
                    message=(
                        f"예정 산출물({states[expected].label})과 실제 기록이 달라요. "
                        "확인 자료를 기록해 주세요."
                    ),
                )

        def paths_from(state):
            result, _ = enumerate_paths(
                value, material, form, None, 8, start_state=state.key if state else None
            )
            if result.budget_exhausted or result.depth_limited:
                raise TreatmentError("next-step-limit", "공정 탐색 한도를 초과했습니다.")
            return result.paths

        current = project_next_step(
            value,
            paths_from(current_state),
            [] if observed else completed,
            metadata,
            request.origin,
            observed_state=current_state,
            initial_form=form if not completed else None,
            recycling_types=request.recycling_types if not completed else None,
        )
        if request.preview_transition is None:
            return current
        planned = next(
            (
                option
                for option in current.options
                if option.transition_key == request.preview_transition
            ),
            None,
        )
        if planned is None:
            raise TreatmentError(
                "invalid-transition", "현재 공정에서 이어지는 예정 공정을 확인해 주세요."
            )
        expected = states[planned.output_state.key]
        return project_next_step(
            value,
            paths_from(expected),
            [],
            {**metadata, "basis": "expected_output"},
            request.origin,
            observed_state=expected,
        )

    return project(reference_data)


def project_next_step(
    value,
    paths,
    completed,
    base,
    origin,
    *,
    observed_state=None,
    initial_form=None,
    recycling_types=None,
):
    states = {state.key: state for state in value.states}
    facilities = {facility.key: facility for facility in value.facilities}
    sources = {source.key: source for source in value.sources}

    def state_label(key):
        return {"key": key, "label": states[key].label}

    def links(keys):
        return [
            {
                "publisher": sources[key].publisher,
                "url": sources[key].url,
                "locator": sources[key].locator,
            }
            for key in sorted(set(keys))
        ]

    options = {}
    can_finish = bool(observed_state and observed_state.is_output)
    current = {observed_state.key} if observed_state else set()
    previews = {}
    index = len(completed)
    for path in paths:
        if [transition.key for transition, _ in path[:index]] != completed:
            continue
        current.add(path[index - 1][0].output_state if index else path[0][0].input_state)
        if len(path) == index:
            can_finish = True
            continue
        transition, capability = path[index]
        remaining = tuple(transition.key for transition, _ in path[index:])
        previews.setdefault(
            remaining,
            [
                {"transition_key": transition.key, "label": transition.label}
                for transition, _ in path[index:]
            ],
        )
        option = options.setdefault(
            transition.key,
            {
                "transition_key": transition.key,
                "label": transition.label,
                "input_state": state_label(transition.input_state),
                "output_state": state_label(transition.output_state),
                "operation_steps": transition.operation_steps,
                "checks": list(dict.fromkeys(transition.conditions + transition.risk_checks)),
                "sources": links(transition.source_ids),
                "recycling_types": search_recycling_types(transition.key, recycling_types),
                "web_search_form": (
                    initial_form or next(iter(states[transition.input_state].input_forms), "washed")
                    if transition.key in PP_SEARCH_TYPES
                    else None
                ),
                "facilities": {},
            },
        )
        if capability and capability.key not in option["facilities"]:
            facility = facilities[capability.facility]
            location, location_url = facility_location(facility)
            review_form = initial_form
            if observed_state and transition.input_state == observed_state.key:
                forms = observed_state.input_forms
                published = capability.input_profile.form_examples
                review_form = next((form for form in forms if form in published), None)
                if review_form is None and len(forms) == 1:
                    review_form = forms[0]
            option["facilities"][capability.key] = {
                "capability_key": capability.key,
                "facility_key": facility.key,
                "label": facility.label,
                "region": facility.region,
                "address": facility.address,
                "evidence_basis": capability.basis,
                "checks": capability.conditions,
                "sources": links(capability.source_ids),
                "intake_review": (
                    review_intake(capability, review_form, links) if review_form else None
                ),
                "location": location,
                "location_source_url": location_url,
                "straight_line_distance_km": straight_line_km(
                    (origin.latitude, origin.longitude) if origin else None,
                    tuple(location.values()) if location else None,
                ),
            }
    if not current and completed:
        raise TreatmentError(
            "invalid-progress", "완료한 공정이 현재 공정 경로와 일치하지 않습니다."
        )
    items = [
        {**option, "facilities": list(option["facilities"].values())} for option in options.values()
    ]
    rank_facilities(items, first_handoff=initial_form is not None)
    preview_keys = sorted(previews, key=lambda keys: (-len(keys), keys))
    prefixes = {keys[:length] for keys in previews for length in range(1, len(keys))}
    full_previews = [previews[keys] for keys in preview_keys if keys not in prefixes][:8]
    if items:
        status, message = "candidates", "현재 상태에서 바로 이어지는 공정의 조사 후보입니다."
        if observed_state:
            message = "기록된 산출물로 찾은 후보입니다. 순도와 중량은 업체에 확인하세요."
    elif can_finish:
        status, message = "end_of_route", "현재 공정 자료에 등록된 마지막 산출 상태입니다."
    else:
        status, message = "no_route", "입력 상태에서 이어지는 검수된 경로를 찾지 못했습니다."
    return NextStepResponse(
        **base,
        status=status,
        current_state=state_label(next(iter(current))) if len(current) == 1 else None,
        can_finish=can_finish,
        options=items,
        process_previews=full_previews,
        message=message,
    )


def facility_location(facility):
    if facility.latitude is not None and facility.longitude is not None:
        return {"latitude": facility.latitude, "longitude": facility.longitude}, None
    if facility.key in MAP_POINTS:
        lat, lon, url = MAP_POINTS[facility.key]
        return {"latitude": lat, "longitude": lon}, url
    return None, None


def review_intake(capability, form, links):
    profile = capability.input_profile
    if capability.basis != "published_site_process":
        evidence = "site_process_unconfirmed"
        check = "이 사업장에서 해당 재질과 형태를 처리하는지 먼저 확인하세요."
    elif form in profile.form_examples:
        evidence = "site_example"
        check = "이번 물량의 허용 이물·수분 기준과 인수 가능 여부를 확인하세요."
    else:
        evidence = "form_not_documented"
        check = "현재 형태를 반입할 수 있는지와 필요한 전처리를 먼저 확인하세요."
    return {
        "form_evidence": evidence,
        "next_check": check,
        "sources": links(profile.source_ids),
        "input_form": form,
    }


def rank_facilities(options, *, first_handoff=False):
    """Rank distinct physical sites across all immediate transitions."""

    def needs_site_review(facility):
        return first_handoff and facility["evidence_basis"] != "published_site_process"

    def order(facility):
        distance = facility["straight_line_distance_km"]
        return (
            needs_site_review(facility),
            facility["distance_rank"] or 6,
            distance if first_handoff and distance is not None else float("inf"),
            facility["capability_key"],
        )

    distances = {
        facility["facility_key"]: facility["straight_line_distance_km"]
        for option in options
        for facility in option["facilities"]
        if facility["straight_line_distance_km"] is not None and not needs_site_review(facility)
    }
    keys = sorted(distances, key=lambda key: (distances[key], key))[:5]
    ranks = {key: i for i, key in enumerate(keys, 1)}
    for option in options:
        for facility in option["facilities"]:
            facility["distance_rank"] = (
                None if needs_site_review(facility) else ranks.get(facility["facility_key"])
            )
        option["facilities"].sort(key=order)
