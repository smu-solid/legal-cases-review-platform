from __future__ import annotations

import uuid
from dataclasses import dataclass

TEST_PASSWORD = "correct horse battery staple"


@dataclass(frozen=True)
class AdminIdentity:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    email: str
    password: str


@dataclass(frozen=True)
class ReviewIdentity:
    user_id: uuid.UUID
    email: str
    password: str
