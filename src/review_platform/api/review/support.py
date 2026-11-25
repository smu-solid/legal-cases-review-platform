"""Shared helpers for review HTTP route modules."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from fastapi import Query

from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.service import ReviewService

QueueStatusFilter = Annotated[Literal["available", "assigned", "completed"] | None, Query()]


class ReviewContext(Protocol):
    review: ReviewService
    artifact_store: ArtifactStore | None
