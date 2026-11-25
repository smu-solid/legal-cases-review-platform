"""Generate a deterministic dataset of fictional cases and document evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from html import escape
from pathlib import Path

from review_platform.dataset.types import (
    InputCandidate,
    InputCase,
    InputEvidence,
    InputField,
    InputRelation,
)
from review_platform.review.source_render import plain_text_from_safe_html, render_source_document


def generate(path: Path, *, count: int = 12) -> None:
    if not 2 <= count <= 10000:
        raise ValueError("case count must be between 2 and 10000")
    if path.exists():
        raise FileExistsError("refusing to overwrite an existing dataset")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript("""PRAGMA foreign_keys=ON;
        PRAGMA user_version=1;
        CREATE TABLE documents(sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64),html TEXT NOT NULL);
        CREATE TABLE cases(
            collection TEXT NOT NULL, external_id TEXT NOT NULL,
            document_sha256 TEXT NOT NULL REFERENCES documents(sha256),
            subject TEXT NOT NULL, judgment_date TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(collection,external_id));
        """)
        for index in range(1, count + 1):
            collection = "sample_a" if index % 2 else "sample_b"
            title = f"Example Trading {index:02d} v Sample Services {index:02d}"
            citation = f"[2024] DEMO {index}"
            date = f"2024-{(index - 1) % 12 + 1:02d}-15"
            subject = "Contract and delivery" if index % 2 else "Property and access"
            other = f"[2023] DEMO {index + 100}"
            paragraphs = [
                "Fictional demonstration document 🧪",
                title,
                citation,
                f"Judgment date: {date}",
                f"Court: Demonstration Court. Subject: {subject}.",
                f"This fictional judgment concerns order {index}. "
                "The parties agreed to deliver demonstration goods.",
                f"The court considered {other} and section 3 of the Example Agreements Act.",
                "The appeal was dismissed. All names, facts, authorities and statutes "
                "in this document are fictional.",
            ]
            html = (
                '<article data-review-document="true">'
                + "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
                + "</article>"
            )
            sha = hashlib.sha256(html.encode()).hexdigest()
            rendered = render_source_document(source_system=collection, raw_html=html)
            text = plain_text_from_safe_html(collection, rendered.safe_html)

            def evidence(value: str, text: str = text, sha: str = sha) -> list[InputEvidence]:
                start = text.index(value)
                return [
                    InputEvidence(
                        "quote", value, start, start + len(value), None, None, sha, True, "document"
                    )
                ]

            def field(name: str, value: str, quote: str) -> InputField:
                candidate = InputCandidate(
                    "deterministic", "supported", value, "Synthetic extracted value.", None
                )
                return InputField(name, value, candidate, None, evidence(quote))

            fields = [
                field("cases.title_raw", title, title),
                field("cases.citation_neutral", citation, citation),
                field("cases.j_date", date, date),
                field("cases.subject", subject, subject),
                field("cases.court_id", "Demonstration Court", "Demonstration Court"),
            ]
            if index % 3 == 0:
                fields[0] = field("cases.title_raw", f"Incorrect title {index}", title)
            relations = [
                InputRelation(
                    "cited_case",
                    "rel_citations",
                    f"CIT-{index}",
                    "Cited case",
                    other,
                    {"to_case_ext": other},
                    evidence(other),
                ),
                InputRelation(
                    "statute_reference",
                    "rel_statutes",
                    f"ACT-{index}",
                    "Statute reference",
                    "Example Agreements Act, section 3",
                    {"to_statute_ext": "Example Agreements Act", "section_cited": "3"},
                    evidence("section 3 of the Example Agreements Act"),
                ),
            ]
            case = InputCase(
                external_id=f"CASE-{index:04d}",
                source_system=collection,
                source_document_id=f"DOCUMENT-{index:04d}",
                sha256=sha,
                title=title,
                fields=fields,
                relations=relations,
            )
            connection.execute("INSERT INTO documents VALUES (?,?)", (sha, html))
            connection.execute(
                "INSERT INTO cases VALUES (?,?,?,?,?,?)",
                (
                    collection,
                    case.external_id,
                    sha,
                    subject,
                    date,
                    json.dumps(
                        asdict(case), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ),
                ),
            )
        connection.commit()
    except Exception:
        connection.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("fixtures/demo.sqlite"))
    parser.add_argument("--cases", type=int, default=12)
    args = parser.parse_args()
    generate(args.output, count=args.cases)


if __name__ == "__main__":
    main()
