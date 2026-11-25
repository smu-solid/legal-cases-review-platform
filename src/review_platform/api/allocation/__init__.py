"""Allocation administration route package."""

from review_platform.api.allocation.router import create_allocation_router
from review_platform.api.allocation.support import AllocationContext

__all__ = ["AllocationContext", "create_allocation_router"]
