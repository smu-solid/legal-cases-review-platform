"""Case submission."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from review_platform.review.schemas.common import ReviewModel


class CaseSubmissionResponse(ReviewModel):
    case_id: str
    campaign_id: uuid.UUID
    submitted_at: datetime
    replayed: bool = False
    schema_version: Literal["case-submission/v1"] = "case-submission/v1"
