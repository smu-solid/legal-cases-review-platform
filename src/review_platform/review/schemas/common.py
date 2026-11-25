"""Shared schema primitives for review API contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


SubjectKind = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")]
ReviewKind = Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")]
