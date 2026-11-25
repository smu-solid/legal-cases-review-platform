from __future__ import annotations


def preferred_annotation(bundle: dict[str, object]) -> dict[str, object]:
    candidates = list(bundle["candidates"])  # type: ignore[arg-type]
    return {
        "outcome": "candidate_a_preferred",
        "assessments": [
            {"candidate_id": candidates[0]["id"], "assessment": "correct"},  # type: ignore[index]
            {"candidate_id": candidates[1]["id"], "assessment": "incorrect"},  # type: ignore[index]
        ],
        "evidence_ids": [],
    }


def alternate_annotation(bundle: dict[str, object]) -> dict[str, object]:
    candidates = list(bundle["candidates"])  # type: ignore[arg-type]
    return {
        "outcome": "candidate_b_preferred",
        "assessments": [
            {"candidate_id": candidates[0]["id"], "assessment": "incorrect"},  # type: ignore[index]
            {"candidate_id": candidates[1]["id"], "assessment": "correct"},  # type: ignore[index]
        ],
        "evidence_ids": [],
    }
