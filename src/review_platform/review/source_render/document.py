"""Sanitized HTML fragments and deterministic document text coordinates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from html import escape

import lxml.html  # type: ignore[import-untyped]
import nh3
from lxml.html import HtmlElement

from review_platform.common.text_coordinates import utf16_length

BLOCKS = frozenset(
    {
        "p",
        "div",
        "article",
        "section",
        "main",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "tr",
        "blockquote",
        "pre",
    }
)
TAGS = set(BLOCKS) | {
    "strong",
    "em",
    "b",
    "i",
    "u",
    "sup",
    "sub",
    "span",
    "br",
    "a",
    "ul",
    "ol",
    "table",
    "thead",
    "tbody",
    "th",
    "td",
    "code",
}


@dataclass(frozen=True)
class TextSlot:
    owner: HtmlElement
    attribute: str
    index: int
    character: str


def project_text(root: HtmlElement) -> tuple[str, list[TextSlot | None]]:
    output: list[str] = []
    slots: list[TextSlot | None] = []
    pending: list[TextSlot | None] = []
    block_break = False

    def characters(owner: HtmlElement, attribute: str) -> None:
        nonlocal block_break
        for index, char in enumerate(getattr(owner, attribute) or ""):
            slot = TextSlot(owner, attribute, index, char)
            if char.isspace():
                pending.append(slot)
                continue
            if output and block_break:
                output.extend(["\n", "\n"])
                slots.extend([None, None])
            elif output and pending:
                output.append(" ")
                slots.append(pending[0])
            pending.clear()
            block_break = False
            output.append(char)
            slots.append(slot)

    def visit(element: HtmlElement) -> None:
        nonlocal block_break
        if element.tag in BLOCKS and output:
            block_break = True
        characters(element, "text")
        for child in element:
            if isinstance(child.tag, str):
                if child.tag in {"style", "script"}:
                    pass
                elif child.tag == "br":
                    pending.append(None)
                else:
                    visit(child)
            characters(child, "tail")
        if element.tag in BLOCKS and output:
            block_break = True

    visit(root)
    return "".join(output), slots


def parse_fragment(html: str) -> HtmlElement:
    return lxml.html.fragment_fromstring(
        html, create_parent="div", parser=lxml.html.HTMLParser(huge_tree=True, no_network=True)
    )


def plain_text_from_safe_html(source_system: str, safe_html: str) -> str:
    return project_text(parse_fragment(safe_html))[0]


@dataclass(frozen=True)
class RenderedArtifact:
    render_profile: str
    render_version: int
    render_mode: str
    safe_html: str
    anchor_map_json: str
    content_digest: str
    anchor_map_digest: str
    mime_type: str = "text/html"

    @property
    def size_bytes(self) -> int:
        return len(self.safe_html.encode("utf-8"))


def render_source_document(
    *, source_system: str, raw_html: str, approved_href_map: dict[str, str] | None = None
) -> RenderedArtifact:
    if len(raw_html.encode("utf-8")) > 16 * 1024 * 1024:
        raise ValueError("document exceeds size limit")
    if not raw_html.strip():
        raise ValueError("document is empty")
    root = lxml.html.fromstring(
        raw_html, parser=lxml.html.HTMLParser(huge_tree=True, no_network=True)
    )
    articles = root.xpath("//article[@data-review-document]")
    if len(articles) > 1:
        raise ValueError("document must have one canonical article")
    if articles:
        root = articles[0]
    raw = lxml.html.tostring(root, encoding="unicode")
    safe = nh3.clean(
        raw,
        tags=TAGS,
        attributes={"a": {"href"}},
        clean_content_tags={"script", "style"},
        link_rel=None,
    )
    fragment = parse_fragment(safe)
    for link in fragment.iter("a"):
        if not (link.get("href") or "").startswith("#"):
            link.attrib.pop("href", None)
    safe = escape(fragment.text or "", quote=False) + "".join(
        lxml.html.tostring(c, encoding="unicode", with_tail=True) for c in fragment
    )
    text, _slots = project_text(fragment)
    cursor = 0
    blocks = []
    for index, block in enumerate(text.split("\n\n")):
        if block:
            blocks.append(
                {
                    "anchor_id": f"block-{index + 1}",
                    "char_start": cursor,
                    "char_end": cursor + utf16_length(block),
                }
            )
        cursor += utf16_length(block) + 2
    anchors = json.dumps({"anchors": blocks}, sort_keys=True, separators=(",", ":"))

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    return RenderedArtifact(
        "generic_document", 1, "sanitized_html", safe, anchors, digest(safe), digest(anchors)
    )
