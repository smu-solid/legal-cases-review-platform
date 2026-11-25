"""Private live checks and serialized submission enforcement using the real HTTP routes."""

import asyncio
import uuid

import pytest

from tests.support.citation_http import extracted_body, feedback, proposal_path, substring_relation
from tests.support.proposals import headers, proposal_workspace, valid_body

__all__ = ["proposal_workspace", "substring_relation"]


@pytest.mark.anyio
@pytest.mark.parametrize("group", ["cited_cases", "statutes_cited"])
async def test_duplicate_drafts_ownership_self_exclusion_and_submitted_lock(
    proposal_workspace, group
):
    clients, tokens, bases, *_ = proposal_workspace
    a, b = clients
    bundle = (await a.get(bases[0] + "/grouped-bundle")).json()
    body = valid_body(bundle, group)
    one, two = str(uuid.uuid4()), str(uuid.uuid4())
    r = await a.put(proposal_path(bases[0], one, "draft"), json=body, headers=headers(tokens[0]))
    assert r.status_code == 200, r.text
    assert not (await feedback(a, bases[0], tokens[0], one, body))["conflicts"]
    check = await feedback(a, bases[0], tokens[0], two, body)
    assert check["conflicts"][0]["kind"] == "confirmed"
    assert check["conflicts"][0]["item_id"] == one
    assert not (await feedback(b, bases[1], tokens[1], two, body))["conflicts"]
    acknowledged = {
        **body,
        "duplicate_acknowledgement": {
            "fingerprint": check["fingerprint"],
            "reason": "Cannot bypass an exact duplicate",
        },
    }
    assert (
        await a.put(proposal_path(bases[0], two), json=acknowledged, headers=headers(tokens[0]))
    ).status_code == 422
    assert (
        await a.put(proposal_path(bases[0], two, "draft"), json=body, headers=headers(tokens[0]))
    ).status_code == 200
    assert (
        await b.post(
            proposal_path(bases[1], one, "duplicate-check"), json=body, headers=headers(tokens[1])
        )
    ).status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("group", ["cited_cases", "statutes_cited"])
@pytest.mark.parametrize("existing_state", ["draft", "submitted"])
@pytest.mark.parametrize(
    "value,start,end,duplicate",
    [
        ("Different value", 0, 5, False),
        ("[2024] SGCA 7", 6, 10, True),
        ("[2024] SGCA 7", 2, 7, True),
        ("Named authority [2024] SGCA 7", 6, 10, True),
        ("[2024] SGCA", 6, 10, True),
    ],
)
async def test_saved_additions_are_compared_by_value_independently_of_ranges(
    proposal_workspace, group, existing_state, value, start, end, duplicate
):
    clients, tokens, bases, *_ = proposal_workspace
    a, token, base = clients[0], tokens[0], bases[0]
    body = valid_body((await a.get(base + "/grouped-bundle")).json(), group)
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    assert (
        await a.put(proposal_path(base, first, existing_state), json=body, headers=headers(token))
    ).status_code == 200
    other = {
        **body,
        "value": value,
        "provenance": [{**body["provenance"][0], "char_start": start, "char_end": end}],
    }
    check = await feedback(a, base, token, second, other)
    assert bool(check["conflicts"]) is duplicate
    response = await a.put(proposal_path(base, second), json=other, headers=headers(token))
    assert response.status_code == (422 if duplicate else 200), response.text
    if duplicate:
        assert check["conflicts"][0]["item_id"] == first
        assert response.json()["code"] == "citation_duplicate"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "substring_relation",
    [(origin, field) for origin in ("extracted",) for field in ("value", "provenance")],
    indirect=True,
)
async def test_normalized_substrings_block_added_items_without_saving_first(
    substring_relation, proposal_workspace
):
    field, citation, origin = substring_relation
    clients, tokens, bases, *_ = proposal_workspace
    client, token, base = clients[0], tokens[0], bases[0]
    bundle = (await client.get(base + "/grouped-bundle")).json()
    extracted = next(g for g in bundle["field_groups"] if g["group_id"] == "cited_cases")["items"][
        0
    ]
    body = extracted_body(bundle, extracted)
    body["value"] = (
        "Calico Printers’ Association Ltd v Barclays Bank " + citation
        if field == "value"
        else "Different proposed citation"
    )
    pid = str(uuid.uuid4())
    check = await feedback(client, base, token, pid, body)
    assert [c["item_id"] for c in check["conflicts"]] == [extracted["review_unit_id"]]
    assert not (await client.get(base + "/grouped-bundle")).json()["reviewer_additions"]
    response = await client.put(proposal_path(base, pid), json=body, headers=headers(token))
    assert response.status_code == 422 and response.json()["code"] == "citation_duplicate"
    saved = await client.put(proposal_path(base, pid, "draft"), json=body, headers=headers(token))
    assert saved.status_code == 200, saved.text
    # Removing the matching text removes the warning, even before another save.
    body["value"] = "Different proposed citation"
    body["provenance"] = []
    assert not (await feedback(client, base, token, pid, body))["conflicts"]


@pytest.mark.anyio
@pytest.mark.parametrize("group", ["cited_cases", "statutes_cited"])
async def test_original_remains_checked_after_correction_and_conflicting_changes(
    proposal_workspace, group
):
    clients, tokens, bases, *_ = proposal_workspace
    a, token, base = clients[0], tokens[0], bases[0]
    bundle = (await a.get(base + "/grouped-bundle")).json()
    extracted = next(g for g in bundle["field_groups"] if g["group_id"] == group)["items"][0]
    # Use this field's source snapshot for both the addition and field submission.
    base = base.rsplit("/", 1)[0] + "/" + extracted["assignment_id"]
    bundle = (await a.get(base + "/grouped-bundle")).json()
    body = extracted_body(bundle, extracted, group)
    pid = str(uuid.uuid4())
    check = await feedback(a, base, token, pid, body)
    assert check["conflicts"][0]["kind"] == "confirmed"
    path = base.rsplit("/", 1)[0] + "/" + extracted["assignment_id"] + "/answer/"
    correction = {
        "value_correct": False,
        "provenance_correct": True,
        "corrected_value_display": "Replacement citation",
        "corrected_value": "Replacement citation",
    }
    r = await a.put(
        path + "draft", json=correction, headers=headers(token, extracted["lock_version"])
    )
    assert r.status_code == 200, r.text
    check = await feedback(a, base, token, pid, body)
    assert check["conflicts"][0]["item_id"] == extracted["review_unit_id"]
    r = await a.put(proposal_path(base, pid), json=body, headers=headers(token))
    assert r.status_code == 422 and r.json()["code"] == "citation_duplicate", r.text
    # Duplicates may still be saved as drafts, but cannot be submitted or bypassed by a correction.
    r = await a.put(proposal_path(base, pid, "draft"), json=body, headers=headers(token))
    assert r.status_code == 200, r.text
    correction.update(corrected_value=body["value"], corrected_value_display=body["value"])
    r = await a.post(
        path + "submit", json=correction, headers=headers(token, extracted["lock_version"] + 1)
    )
    assert r.status_code == 422 and r.json()["code"] == "citation_duplicate", r.text
    reverted = await a.post(
        path + "submit",
        json={"value_correct": True, "provenance_correct": True},
        headers=headers(token, extracted["lock_version"] + 1),
    )
    assert reverted.status_code == 422 and reverted.json()["code"] == "citation_duplicate"


@pytest.mark.anyio
@pytest.mark.parametrize("group", ["cited_cases", "statutes_cited"])
async def test_concurrent_new_duplicates_only_one_submits(proposal_workspace, group):
    clients, tokens, bases, *_ = proposal_workspace
    a, token, base = clients[0], tokens[0], bases[0]
    body = valid_body((await a.get(base + "/grouped-bundle")).json(), group)
    results = await asyncio.gather(
        *[
            a.put(proposal_path(base, uuid.uuid4()), json=body, headers=headers(token))
            for _ in range(2)
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 422], [r.text for r in results]


@pytest.mark.anyio
async def test_incomplete_correction_feedback_overrides_and_source_versions(proposal_workspace):
    clients, tokens, bases, *_ = proposal_workspace
    a, token, base = clients[0], tokens[0], bases[0]
    bundle = (await a.get(base + "/grouped-bundle")).json()
    extracted = next(g for g in bundle["field_groups"] if g["group_id"] == "cited_cases")["items"][
        0
    ]
    pid = str(uuid.uuid4())
    body = {
        **extracted_body(bundle, extracted),
        "answer_overrides": {
            extracted["review_unit_id"]: {
                "value_correct": False,
                "provenance_correct": True,
                "comment": "Incomplete correction",
            },
        },
    }
    check = await feedback(a, base, token, pid, body)
    assert check["conflicts"][0]["item_id"] == extracted["review_unit_id"]
    body["answer_overrides"][extracted["review_unit_id"]]["corrected_value_display"] = "Replacement"
    check = await feedback(a, base, token, pid, body)
    assert check["conflicts"][0]["item_id"] == extracted["review_unit_id"]
    # Preview overrides never overwrite a saved field or bypass submission validation.
    del body["answer_overrides"]
    r = await a.put(proposal_path(base, pid), json=body, headers=headers(token))
    assert r.status_code == 422 and r.json()["code"] == "citation_duplicate"
    path = base.rsplit("/", 1)[0] + "/" + extracted["assignment_id"] + "/answer/submit"
    bad = {
        "value_correct": False,
        "provenance_correct": False,
        "corrected_value": "Replacement",
        "corrected_value_display": "Replacement",
        "corrected_provenance_spans": [
            {
                "evidence_window_id": extracted["evidence_window_ids"][0],
                "char_start": 0,
                "char_end": 5,
                "source_snapshot_id": bundle["source_render"]["source_snapshot_id"],
                "source_version": "0" * 64,
            }
        ],
    }
    r = await a.post(path, json=bad, headers=headers(token, extracted["lock_version"]))
    assert r.status_code == 422 and r.json()["code"] == "proposal_provenance_invalid", r.text


@pytest.mark.anyio
@pytest.mark.parametrize("group", ["cited_cases", "statutes_cited"])
@pytest.mark.parametrize("different_range", [False, True])
async def test_case_submission_revalidates_legacy_duplicate_proposals(
    proposal_workspace, database, group, different_range
):
    from sqlalchemy import select

    from review_platform.review.models.proposals import ReviewerAddedProposal

    clients, tokens, bases, assignments, _ = proposal_workspace
    a, token, base = clients[0], tokens[0], bases[0]
    body = valid_body((await a.get(base + "/grouped-bundle")).json(), group)
    pid = uuid.uuid4()
    r = await a.put(proposal_path(base, pid), json=body, headers=headers(token))
    assert r.status_code == 200, r.text
    for aid in assignments[0]:
        r = await a.post(
            base.rsplit("/", 1)[0] + "/" + aid + "/answer/submit",
            json={"value_correct": True, "provenance_correct": True},
            headers=headers(token),
        )
        assert r.status_code == 201, r.text
    # Simulate a pre-feature submitted duplicate; no mutation of either submitted proposal.
    with database.session() as session, session.begin():
        original = session.scalar(
            select(ReviewerAddedProposal).where(ReviewerAddedProposal.id == pid)
        )
        values = {
            column.name: getattr(original, column.name)
            for column in ReviewerAddedProposal.__table__.columns
        }
        values["id"] = uuid.uuid4()
        if different_range:
            values["provenance_json"] = [{**body["provenance"][0], "char_start": 6, "char_end": 10}]
        session.add(ReviewerAddedProposal(**values))
    r = await a.post(base + "/case-submit", headers=headers(token))
    assert r.status_code == 422 and r.json()["code"] == "citation_duplicate", r.text
    current = (await a.get(base + "/grouped-bundle")).json()
    assert not current["case_submitted"] and len(current["reviewer_additions"]) == 2
