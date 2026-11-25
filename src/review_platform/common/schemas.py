"""Shared Pydantic base models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Reject unknown fields on every request and response body."""

    model_config = ConfigDict(extra="forbid")


class StatusResponse(StrictModel):
    status: str
