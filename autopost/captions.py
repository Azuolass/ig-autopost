"""Turn the text of an instagram_caption PDF into a clean Instagram caption.

The PDFs in Drive come in (at least) two layouts:

    20 October 2026 Post 2            SUCCESS HUNTERS / 20.10.2026 / POST 3
    You Vs You Stephen Curry          Lock In Mike Tyson
    Instagram caption                 focus looks quiet.
    your last version is ...          ...
    shop now. "...". link in bio.     shop now. "...". link in bio.
                                      instagram caption

Header/footer lines are dropped, lines that the PDF wrapped mid-sentence are
joined back together, and real paragraphs are kept as separate lines.
"""
from __future__ import annotations

import re

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december"
)

_HEADER_PATTERNS = [
    re.compile(r"^\s*instagram caption( updated)?\s*$", re.I),
    re.compile(r"^\s*success hunters\b.*$", re.I),
    re.compile(rf"^\s*\d{{1,2}}\s+({MONTHS})\s+\d{{4}}\b.*$", re.I),
    re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]\d{4}\b.*$"),
    re.compile(r"^\s*post\s*\d+\s*$", re.I),
    re.compile(r"^\s*\d+\s*(puslapis|page)\s*(i[šs]|of)\s*\d+\s*$", re.I),
]

_SENTENCE_END = re.compile(r"[.!?…:\"”)\]]\s*$")
IG_CAPTION_LIMIT = 2200


def _is_header(line: str, title: str | None) -> bool:
    if title and line.strip().lower() == title.strip().lower():
        return True
    return any(p.match(line) for p in _HEADER_PATTERNS)


def clean_caption(raw: str, title: str | None = None) -> str:
    lines = [ln.rstrip() for ln in raw.replace("\r", "").split("\n")]
    kept: list[str] = []
    for ln in lines:
        if not ln.strip():
            kept.append("")
            continue
        if _is_header(ln, title):
            continue
        kept.append(re.sub(r"\s+", " ", ln.strip()))

    # Join lines the PDF wrapped: a line that does not end a sentence continues
    # on the next non-empty line.
    paragraphs: list[str] = []
    buf = ""
    for ln in kept:
        if not ln:
            if buf and _SENTENCE_END.search(buf):
                paragraphs.append(buf)
                buf = ""
            continue
        buf = f"{buf} {ln}".strip() if buf else ln
        if _SENTENCE_END.search(buf):
            paragraphs.append(buf)
            buf = ""
    if buf:
        paragraphs.append(buf)

    caption = "\n".join(p.strip() for p in paragraphs if p.strip())
    if len(caption) > IG_CAPTION_LIMIT:
        raise ValueError(f"caption is {len(caption)} chars, Instagram allows {IG_CAPTION_LIMIT}")
    if not caption:
        raise ValueError("caption came out empty after cleaning")
    return caption


def pdf_to_text(pdf_bytes: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)
