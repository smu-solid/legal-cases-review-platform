"""Shared allocation route types."""

from __future__ import annotations

from typing import Protocol

from review_platform.review.allocation.service import AllocationService


class AllocationContext(Protocol):
    allocation: AllocationService
