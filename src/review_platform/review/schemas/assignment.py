"""Reviewer assignment lifecycle schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from review_platform.review.schemas.common import ReviewModel


class AssignmentSummary(ReviewModel):
    assignment_id: uuid.UUID
    review_unit_id: uuid.UUID
    status: Literal["claimed", "submitted", "released", "revision_requested"]
    lease_expires_at: datetime
    revision_requested_at: datetime | None = None
    revision_reason: str | None = None
    lock_version: int


class ClaimResponse(AssignmentSummary):
    replayed: bool = False


class AssignmentLeaseResponse(AssignmentSummary):
    """Assignment state returned by lease and revision lifecycle actions."""

    replayed: bool = False


class AssignmentRevisionRequestResponse(AssignmentSummary):
    """Manager response after requesting reviewer revision of a submitted assignment."""

    replayed: bool = False
