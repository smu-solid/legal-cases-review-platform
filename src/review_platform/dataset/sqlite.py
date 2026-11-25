"""Validated case inputs and documents from a read-only SQLite dataset."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import date

from pydantic import TypeAdapter

from review_platform.dataset.catalog import DatasetCatalog
from review_platform.dataset.types import (
    InputCandidate,
    InputCase,
    InputEvidence,
    InputField,
    InputRelation,
    MemberValue,
)
from review_platform.review.source_render import plain_text_from_safe_html, render_source_document


class SQLiteDataset(DatasetCatalog):
    def resolve(self, sha256: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT sha256 FROM documents WHERE sha256=?", (sha256,)
            ).fetchone()
        return row[0] if row else None

    def read_html(self, sha256: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT html FROM documents WHERE sha256=?", (sha256,)
            ).fetchone()
        if row is None:
            return None
        html = str(row[0])
        if (
            len(html.encode()) > 16 * 1024 * 1024
            or hashlib.sha256(html.encode()).hexdigest() != sha256
        ):
            raise ValueError("document integrity check failed")
        return html

    def iter_cases(self, *, limit: int | None = None) -> Iterator[InputCase]:
        if limit is not None and limit < 1:
            raise ValueError("case limit must be positive")
        with self.connection() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("unsupported dataset schema version")
            query = "SELECT * FROM cases ORDER BY collection, external_id"
            rows = connection.execute(
                query + (" LIMIT ?" if limit else ""), (limit,) if limit else ()
            ).fetchall()
        for row in rows:
            if self.read_html(row["document_sha256"]) is None:
                raise ValueError("case document is missing")
            date.fromisoformat(row["judgment_date"])
            data = json.loads(row["payload_json"])
            if len(data.get("fields", [])) + len(data.get("relations", [])) > 1000:
                raise ValueError("too many review items")
            validated = TypeAdapter(InputCase).validate_python(data)
            if not validated.external_id or len(validated.external_id) > 100:
                raise ValueError("invalid case identity")
            if (
                data["external_id"] != row["external_id"]
                or data["source_system"] != row["collection"]
                or data["sha256"] != row["document_sha256"]
            ):
                raise ValueError("case metadata identity mismatch")
            fields = []
            for field in data.pop("fields"):
                field = dict(field)
                field["value_candidate"] = InputCandidate(**field["value_candidate"])
                field["model_candidate"] = (
                    InputCandidate(**field["model_candidate"])
                    if field.get("model_candidate")
                    else None
                )
                field["evidence"] = [InputEvidence(**e) for e in field["evidence"]]
                field["member_values"] = tuple(
                    MemberValue(**m) for m in field.get("member_values", [])
                )
                fields.append(InputField(**field))
            relations = []
            for relation in data.pop("relations"):
                relation = dict(relation)
                relation["evidence"] = [InputEvidence(**e) for e in relation["evidence"]]
                relation["contributing"] = tuple(relation.get("contributing", []))
                relations.append(InputRelation(**relation))
            case = InputCase(**data, fields=fields, relations=relations)
            for evidence in [e for field in fields for e in field.evidence] + [
                e for relation in relations for e in relation.evidence
            ]:
                if len(evidence.snippet) > 20000:
                    raise ValueError("evidence exceeds size limit")
                if evidence.source_hash != case.sha256:
                    raise ValueError("evidence belongs to another document")
                if (evidence.char_start is None) != (evidence.char_end is None):
                    raise ValueError("incomplete evidence range")
                if (
                    evidence.char_start is not None
                    and evidence.char_end is not None
                    and not 0 <= evidence.char_start < evidence.char_end
                ):
                    raise ValueError("invalid evidence range")
            raw = self.read_html(case.sha256)
            if raw is None:
                raise ValueError("case document disappeared during import")
            rendered = render_source_document(source_system=case.source_system, raw_html=raw)
            text = plain_text_from_safe_html(case.source_system, rendered.safe_html)
            items: list[InputField | InputRelation] = [*case.fields, *case.relations]
            for item in items:
                for evidence in item.evidence:
                    if evidence.char_end is not None:
                        if evidence.char_end > len(text):
                            raise ValueError("evidence is outside the document")
                        if text[evidence.char_start : evidence.char_end] != evidence.snippet:
                            raise ValueError("evidence range does not match its snippet")
            yield case
