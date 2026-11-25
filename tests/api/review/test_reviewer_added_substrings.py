"""API regressions for parallel citations and original values marked incorrect."""

import uuid
from dataclasses import replace

import pytest

from tests.support.citation_http import feedback, proposal_path
from tests.support.proposals import headers, proposal_workspace, valid_body

__all__ = ["proposal_workspace"]


@pytest.fixture
def parallel_report_relation(monkeypatch):
    from tests.support import proposals as test_reviewer_proposals

    relation = replace(
        test_reviewer_proposals._cited_case_relation(),
        value={
            "to_case_ext": None,
            "resolved_citation_neutral": "[1988] SGHC 37",
            "resolved_title": "Tham Wing Fai Peter v Public Prosecutor",
            "resolved_citation_reporter": "[1988] 1 rep(R) 349; [1988] rep 424",
        },
    )
    monkeypatch.setattr(test_reviewer_proposals, "_cited_case_relation", lambda: relation)


@pytest.mark.anyio
@pytest.mark.parametrize("citation", ["[1988] 1 rep(R) 349", "[1988] rep 424"])
@pytest.mark.parametrize("with_name", [False, True])
async def test_parallel_reports_block_live_checks_and_direct_submission(
    parallel_report_relation, proposal_workspace, citation, with_name
):
    clients, tokens, bases, *_ = proposal_workspace
    client, token, base = clients[0], tokens[0], bases[0]
    bundle = (await client.get(base + "/grouped-bundle")).json()
    existing = next(g for g in bundle["field_groups"] if g["group_id"] == "cited_cases")["items"][0]
    body = {
        **valid_body(bundle),
        "value": f"Peter Tham Wing Fai v PP {citation}" if with_name else citation,
    }
    pid = str(uuid.uuid4())
    # Typing the value alone is enough; marking provenance is not needed to detect the duplicate.
    check = await feedback(client, base, token, pid, {**body, "provenance": []})
    assert [c["item_id"] for c in check["conflicts"]] == [existing["review_unit_id"]]
    submitted = await client.put(proposal_path(base, pid), json=body, headers=headers(token))
    assert submitted.status_code == 422 and submitted.json()["code"] == "citation_duplicate"


@pytest.mark.anyio
@pytest.mark.parametrize("correction_state", ["draft", "submit"])
@pytest.mark.parametrize("replacement", [None, "Different corrected authority"])
async def test_original_value_remains_checked_after_marking_no(
    proposal_workspace, correction_state, replacement
):
    clients, tokens, bases, *_ = proposal_workspace
    client, token, base = clients[0], tokens[0], bases[0]
    bundle = (await client.get(base + "/grouped-bundle")).json()
    existing = next(g for g in bundle["field_groups"] if g["group_id"] == "cited_cases")["items"][0]
    base = base.rsplit("/", 1)[0] + "/" + existing["assignment_id"]
    bundle = (await client.get(base + "/grouped-bundle")).json()
    answer_path = base.rsplit("/", 1)[0] + "/" + existing["assignment_id"] + "/answer/"
    correction = {
        "value_correct": False,
        "provenance_correct": False,
        "comment": "Original marked incorrect",
        "corrected_value": replacement,
        "corrected_value_display": replacement,
        "corrected_provenance_spans": [
            {
                "evidence_window_id": existing["evidence_window_ids"][0],
                **valid_body(bundle)["provenance"][0],
            }
        ],
    }
    result = await client.request(
        "PUT" if correction_state == "draft" else "POST",
        answer_path + correction_state,
        json=correction,
        headers=headers(token, existing["lock_version"]),
    )
    assert result.status_code == (200 if correction_state == "draft" else 201), result.text
    body = {**valid_body(bundle), "value": "Full case name " + existing["extracted_value_display"]}
    pid = str(uuid.uuid4())
    check = await feedback(client, base, token, pid, body)
    assert [c["item_id"] for c in check["conflicts"]] == [existing["review_unit_id"]]
    submitted = await client.put(proposal_path(base, pid), json=body, headers=headers(token))
    assert submitted.status_code == 422 and submitted.json()["code"] == "citation_duplicate"
    saved = await client.put(proposal_path(base, pid, "draft"), json=body, headers=headers(token))
    assert saved.status_code == 200, saved.text
