"""Turn the text of an instagram_caption PDF into a clean Instagram caption.

The PDFs in Drive come in (at least) two layouts:

    20 October 2026 Post 2            SUCCESS HUNTERS / 20.10.2026 / POST 3
    You Vs You Stephen Curry          Lock In Mike Tyson
    Instagram caption                 focus looks quiet.
    your last version is ...          ...
    shop now. "...". link in bio.     shop now. "...". link in bio.
                                      instagram caption

Header/footer lines are dropped, lines that the PDF wrapped are joined back
together, and paragraphs are separated by an empty line, as in the PDF.
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


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ").replace("+", " and ")
    return re.sub(r"[^a-z0-9]+", "", s)


_DOC_HEADER = re.compile(
    r"^[^\n]{0,120}?\binstagram\s+caption\b[\s:|-]*(?:sh\s+\w+\s+daily\b)?[\s:|-]*"
    r"(?:\d{1,2}\s+[a-z]+\s+\d{4}|\d{1,2}[./]\d{1,2}[./]\d{2,4})?\s*", re.I)


def house_case(text: str) -> str:
    """Owner's rule: captions are lowercase; only the product name in quotes keeps its letters."""
    parts = re.split(r'("[^"\n]*"|“[^”\n]*”)', text)
    return "".join(p if i % 2 else p.lower() for i, p in enumerate(parts))


def _is_header(line: str, title: str | None) -> bool:
    if title and _norm(line) == _norm(title):
        return True
    return any(p.match(line) for p in _HEADER_PATTERNS)


def clean_caption(raw: str, title: str | None = None) -> str:
    """raw: one line per PDF line, a blank line where the PDF has a paragraph gap.

    Inside a paragraph, wrapped lines are joined with spaces and lines that end
    a sentence keep their line break; paragraphs are separated by an empty
    line, the way the account's captions are written. A block that
    does not end a sentence is treated as wrapped and joined with the next one.
    """
    blocks: list[list[str]] = [[]]
    for ln in raw.replace("\r", "").split("\n"):
        if not ln.strip():
            if blocks[-1]:
                blocks.append([])
            continue
        if _is_header(ln, title):
            continue
        blocks[-1].append(re.sub(r"\s+", " ", ln.strip()))

    paragraphs: list[str] = []
    buf = ""
    for block in blocks:
        if not block:
            continue
        # inside a paragraph: a line that ends a sentence keeps its line break,
        # a line cut mid-sentence (the PDF wrapped it) is joined with a space
        text = block[0]
        for ln in block[1:]:
            text += ("\n" if _SENTENCE_END.search(text) else " ") + ln
        buf = f"{buf} {text}" if buf else text
        if _SENTENCE_END.search(buf):
            paragraphs.append(buf)
            buf = ""
    if buf:
        paragraphs.append(buf)

    caption = "\n\n".join(p.strip() for p in paragraphs if p.strip())
    # newer caption PDFs print "<Title> / Instagram caption / SH IG DAILY / 29 October 2026"
    # as a header that gets joined into the first sentence
    caption = _DOC_HEADER.sub("", caption, count=1).lstrip()
    caption = house_case(caption)
    if len(caption) > IG_CAPTION_LIMIT:
        raise ValueError(f"caption is {len(caption)} chars, Instagram allows {IG_CAPTION_LIMIT}")
    if not caption:
        raise ValueError("caption came out empty after cleaning")
    return caption


def pdf_to_text(pdf_bytes: bytes) -> str:
    """Text of the PDF, one line per printed line, with a blank line wherever the
    vertical gap to the next line is clearly bigger than normal line spacing
    (that is how the caption documents mark paragraphs)."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_out: list[str] = []
    for page in reader.pages:
        chunks: list[tuple[float, float, str]] = []

        def visit(text, cm, tm, font_dict, font_size):
            if not text or not text.strip():
                return
            # position in page space: tm applied, then cm
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            chunks.append((round(y, 1), x, text))

        page.extract_text(visitor_text=visit)
        if not chunks:
            continue
        # group chunks into lines by y (top of page first)
        lines: list[tuple[float, str]] = []
        for y, x, text in sorted(chunks, key=lambda c: (-c[0], c[1])):
            if lines and abs(lines[-1][0] - y) < 2:
                lines[-1] = (lines[-1][0], lines[-1][1] + text)
            else:
                lines.append((y, text))
        lines = [(y, re.sub(r"\s+", " ", t).strip()) for y, t in lines if t.strip()]
        if not lines:
            continue
        gaps = [lines[i][0] - lines[i + 1][0] for i in range(len(lines) - 1)]
        positive = sorted(g for g in gaps if g > 0)
        line_step = positive[0] if positive else 0
        # Only one spacing in the document: cannot tell wraps from paragraphs by
        # position, so every line becomes its own block and clean_caption joins
        # the ones that do not end a sentence.
        uniform = not positive or positive[-1] <= line_step * 1.45
        out = [lines[0][1]]
        for gap, (_, text) in zip(gaps, lines[1:]):
            if uniform or gap > line_step * 1.45:
                out.append("")
            out.append(text)
        pages_out.append("\n".join(out))
    text = "\n\n".join(pages_out)
    if not text.strip():  # fall back to plain extraction
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return text
