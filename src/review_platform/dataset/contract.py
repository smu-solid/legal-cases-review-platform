"""Typed immutable contract consumed by review imports."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Protocol

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, JsonValue, model_validator

CONTRACT_VERSION = "review-dataset-snapshot/v1"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestSecurity(ContractModel):
    contains_source_path: bool
    url_hosts_are_reserved_invalid: bool
    untrusted_text_is_intentional: bool


class ManifestFile(ContractModel):
    path: str = Field(max_length=100)
    purpose: str = Field(max_length=300)


class SnapshotManifest(ContractModel):
    fixture_set: str = Field(max_length=100)
    contract_version: str = Field(max_length=100)
    tenant_key: str = Field(max_length=80)
    source_mode: Literal["synthetic"]
    created_at: str = Field(max_length=40)
    canonicalization: str = Field(max_length=200)
    contains_real_data: bool
    files: tuple[ManifestFile, ...] = Field(max_length=20)
    security_assertions: ManifestSecurity


class SnapshotTarget(ContractModel):
    external_id: str = Field(max_length=100)
    table: str = Field(max_length=80)
    field: str = Field(max_length=100)


class SourceDocument(ContractModel):
    external_id: str = Field(max_length=100)
    source_system: str = Field(max_length=80)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_type: str = Field(max_length=100)
    source_url: AnyHttpUrl

    @model_validator(mode="after")
    def reserved_url_only(self) -> SourceDocument:
        if self.source_url.host is None or not self.source_url.host.endswith(".invalid"):
            raise ValueError("synthetic source URLs must use a reserved .invalid host")
        return self


class Extraction(ContractModel):
    run_id: str = Field(max_length=100)
    extractor_version: str = Field(max_length=100)
    registry_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    tier: str = Field(max_length=20)
    extractor_name: str = Field(max_length=100)
    value: JsonValue = None
    display_value: str = Field(max_length=10_000)
    validation_status: str | None = Field(default=None, max_length=40)


class EvidenceInput(ContractModel):
    ordinal: int = Field(ge=0, le=100)
    kind: Literal["dom", "line", "regex", "paragraph", "html_tag"]
    location: str = Field(max_length=200)
    snippet: str = Field(max_length=20_000)
    selector: str | None = Field(default=None, max_length=500)
    line_start: int | None = Field(default=None, ge=0)
    line_end: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def ordered_offsets(self) -> EvidenceInput:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line offsets must be ordered")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("character offsets must be ordered")
        return self


class CandidateInput(ContractModel):
    display_label: str = Field(pattern=r"^[A-Z]$")
    validator_kind: str = Field(max_length=40)
    validator_name: str = Field(max_length=100)
    validator_version: str = Field(max_length=100)
    raw_verdict: str = Field(max_length=80)
    normalized_verdict: str = Field(max_length=80)
    value: JsonValue = None
    rationale: str = Field(max_length=10_000)
    supporting_quote: str | None = Field(default=None, max_length=10_000)
    requires_human_review: bool


class SnapshotItem(ContractModel):
    snapshot_id: str = Field(max_length=80)
    captured_at: str = Field(max_length=40)
    source_revision: str = Field(max_length=100)
    source_mode: Literal["synthetic"]
    external_item_key: str = Field(max_length=240)
    target: SnapshotTarget
    source_document: SourceDocument
    extraction: Extraction
    evidence: tuple[EvidenceInput, ...] = Field(max_length=100)
    validator_candidates: tuple[CandidateInput, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def candidate_labels_are_stable(self) -> SnapshotItem:
        if [candidate.display_label for candidate in self.validator_candidates] != ["A", "B"]:
            raise ValueError("candidate labels must be exactly A and B in stable order")
        ordinals = [evidence.ordinal for evidence in self.evidence]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("evidence ordinals must be unique")
        if any(evidence.source_hash != self.source_document.sha256 for evidence in self.evidence):
            raise ValueError("evidence source hashes must match the source document")
        return self


class SnapshotEnvelope(ContractModel):
    contract_version: str = Field(max_length=100)
    fixture_set: str = Field(max_length=100)
    tenant_key: str = Field(max_length=80)
    items: tuple[SnapshotItem, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def item_metadata_is_consistent(self) -> SnapshotEnvelope:
        if any(item.source_mode != "synthetic" for item in self.items):
            raise ValueError("snapshot items must remain synthetic")
        content_keys = [opaque_content_key(item) for item in self.items]
        if len(content_keys) != len(set(content_keys)):
            raise ValueError("snapshot content identities must be unique")
        snapshot_ids = [item.snapshot_id for item in self.items]
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("snapshot IDs must be unique")
        return self


class SnapshotBatch(ContractModel):
    manifest: SnapshotManifest
    envelope: SnapshotEnvelope
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class SnapshotReader(Protocol):
    """The only input capability required by synthetic imports."""

    def load(self, fixture_version: str) -> SnapshotBatch: ...


def opaque_content_key(item: SnapshotItem) -> str:
    """Opaque content key."""

    identity = {
        "contract_version": "review-dataset-snapshot/v1",
        "source_system": item.source_document.source_system,
        "document_sha256": item.source_document.sha256,
        "target_family": item.target.table,
        "target_field": item.target.field,
        # Campaign 1 is metadata-only. A later relation design must supply an owner-approved,
        # canonical relation identity before it can use this runtime contract.
        "relation_identity": None,
    }
    canonical = json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
