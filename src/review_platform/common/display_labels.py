"""Formatting of legal provision markers in imported and persisted candidate labels."""


def section_display(section: str) -> str:
    """Keep an existing section marker; add one only for a bare provision."""
    if section.lower().startswith(("s ", "ss ", "s.", "ss.", "section ")):
        return section
    return f"s {section}"
