"""Shared HTTP workflow scenario support."""

from dataclasses import replace

import pytest

from tests.support.proposals import headers, valid_body


def proposal_path(base, pid, state="submitted"):
    return f"{base}/proposals/{pid}/{state}"


async def feedback(client, base, token, pid, body):
    r = await client.post(
        proposal_path(base, pid, "duplicate-check"), json=body, headers=headers(token)
    )
    assert r.status_code == 200, r.text
    return r.json()


def extracted_body(bundle, extracted, group="cited_cases"):
    return {
        **valid_body(bundle, group),
        "value": extracted["extracted_value_display"],
        "provenance": [
            {k: c[k] for k in ("source_snapshot_id", "source_version", "char_start", "char_end")}
            for c in bundle["provenance_context"]
            if c["item_id"] == extracted["review_unit_id"] and c["kind"] == "Extracted"
        ],
    }


@pytest.fixture
def substring_relation(monkeypatch, request):
    from tests.support import proposals as test_reviewer_proposals

    origin, field = request.param
    relation = test_reviewer_proposals._cited_case_relation()
    citation = "(1931) 145 LT 51 (CA)" if field == "value" else relation.evidence[0].snippet
    relation = replace(
        relation,
        value={
            "to_case_ext": "  " + citation.upper().replace(" ", "  \n") + "  ",
            "resolved_title": "Existing case name",
        },
    )
    monkeypatch.setattr(test_reviewer_proposals, "_cited_case_relation", lambda: relation)
    return field, citation, origin
