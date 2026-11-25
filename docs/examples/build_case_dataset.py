"""Build a one-case SQLite dataset from an HTML judgment and a date to review."""

import hashlib
import json
import sqlite3
from pathlib import Path

from review_platform.dataset.sqlite import SQLiteDataset
from review_platform.review.source_render import plain_text_from_safe_html, render_source_document

# Update these values to use your own HTML and extracted date.
html_path = Path("var/my-judgment.html")
output = Path("var/my-cases.sqlite")
case_id = "MY-CASE-001"
title = "River Trading v Hill Services"
subject = "Contract and delivery"
judgment_date = "2024-02-12"
snippet = "Judgment date: 12 February 2024."

# The collection key is part of the SQLite dataset format.
collection = "sample_a"
if output.exists():
    raise SystemExit(f"{output} already exists. Choose another output file to keep it.")

html = html_path.read_text(encoding="utf-8")
document_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
rendered = render_source_document(source_system=collection, raw_html=html)
text = plain_text_from_safe_html(collection, rendered.safe_html)
if not snippet.strip() or text.count(snippet) != 1:
    raise SystemExit("Choose an evidence passage that appears exactly once in the judgment text.")
start = text.index(snippet)

payload = {
    "external_id": case_id,
    "source_system": collection,
    "source_document_id": f"{case_id}-document",
    "sha256": document_hash,
    "title": title,
    "fields": [
        {
            "field_name": "cases.j_date",
            "display_value": judgment_date,
            "value_candidate": {
                "source_kind": "deterministic",
                "verdict": "supported",
                "value": judgment_date,
                "rationale": "Date taken from the judgment.",
                "supporting_quote": snippet,
            },
            "model_candidate": None,
            "evidence": [
                {
                    "kind": "quote",
                    "snippet": snippet,
                    "source_hash": document_hash,
                    "char_start": start,
                    "char_end": start + len(snippet),
                    "line_start": None,
                    "line_end": None,
                }
            ],
        }
    ],
    "relations": [],
}

with sqlite3.connect(output) as db:
    db.executescript("""
        PRAGMA foreign_keys = ON;
        PRAGMA user_version = 1;
        CREATE TABLE documents (
            sha256 TEXT PRIMARY KEY CHECK (length(sha256) = 64),
            html TEXT NOT NULL
        );
        CREATE TABLE cases (
            collection TEXT NOT NULL,
            external_id TEXT NOT NULL,
            document_sha256 TEXT NOT NULL REFERENCES documents(sha256),
            subject TEXT NOT NULL,
            judgment_date TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (collection, external_id)
        );
    """)
    db.execute("INSERT INTO documents VALUES (?, ?)", (document_hash, html))
    db.execute(
        "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?)",
        (
            collection,
            case_id,
            document_hash,
            subject,
            judgment_date,
            json.dumps(payload),
        ),
    )

cases = list(SQLiteDataset(output).iter_cases())
print(f"Ready to import {cases[0].external_id} from {output}.")
