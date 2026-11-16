import pytest
from pydantic import ValidationError

from app.domains.treatment.intake import IntakeBatchResult


def test_gap_contract_survives_storage_json_and_legacy_responses():
    response = IntakeBatchResult.model_validate(
        {
            "results": {
                "old": {"status": "needs_evidence", "next_check": "자료 확인"},
                "new": {
                    "status": "needs_evidence",
                    "next_check": "자료 확인",
                    "evidence_gaps": ["output_only", "input_form_unproven"],
                },
            }
        }
    )
    stored = IntakeBatchResult.model_validate_json(response.model_dump_json())
    assert stored.results["old"].evidence_gaps == []
    assert stored.results["new"].evidence_gaps == ["output_only", "input_form_unproven"]
    assert not stored.results["new"].dispatch_approved
    with pytest.raises(ValidationError):
        IntakeBatchResult.model_validate(
            {
                "results": {
                    "x": {
                        "status": "needs_evidence",
                        "next_check": "자료 확인",
                        "evidence_gaps": ["approved"],
                    }
                }
            }
        )
