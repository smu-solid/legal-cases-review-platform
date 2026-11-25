"""Conversions between Python character indices and browser UTF-16 coordinates."""


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def codepoint_range(text: str, start: int, end: int) -> tuple[int, int]:
    encoded = text.encode("utf-16-le")
    if not 0 <= start < end <= len(encoded) // 2:
        raise ValueError("invalid text range")
    try:
        prefix = encoded[: start * 2].decode("utf-16-le")
        selected = encoded[start * 2 : end * 2].decode("utf-16-le")
    except UnicodeDecodeError as exc:
        raise ValueError("text range splits a surrogate pair") from exc
    return len(prefix), len(prefix) + len(selected)
