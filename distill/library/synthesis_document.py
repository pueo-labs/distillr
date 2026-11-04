"""Reading copy of a synthesis: superscript citations and a source list.

The Markdown synthesis stays the inspectable record, with bracketed sources
in the prose. This module renders a separate Word document. Each distinct
source is numbered at first use, later mentions reuse that number, and the
source list is printed once at the end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from docx import Document as new_document
from docx.document import Document as DocxDocument
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.section import Section
from docx.shared import Inches, Pt, RGBColor
from docx.styles.style import ParagraphStyle
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from distill.library.paths import atomic_write_bytes

__all__ = [
    "ReadingSynthesis",
    "SynthesisSource",
    "prepare_reading_synthesis",
    "write_synthesis_document",
]

_NAVY = RGBColor(0x1F, 0x3A, 0x5F)
_ACCENT = RGBColor(0x1F, 0x4E, 0x79)
_INK = RGBColor(0x33, 0x33, 0x33)
_MUTED = RGBColor(0x66, 0x66, 0x66)
_RULE = "D0D7E2"
_HEADER_FILL = "1F3A5F"
_BAND = "F4F7FB"
_STRENGTH = frozenset({"C", "S", "I", "G"})
_BADGES = frozenset(
    {"Analysis", "Confirmed", "Estimated", "High", "Low", "Medium", "Reported", "Speculated"}
)
_SEPARATORS = ("\u2014", "\u2013", " - ")
_YT_ID = re.compile(r"\bYT\s+([A-Za-z0-9_-]{6,20})\b", re.IGNORECASE)
_ARXIV_URL = re.compile(
    r"https?://arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)
_ARXIV_LABEL = re.compile(r"\barxiv[:\s]+(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.IGNORECASE)
_LEARN = re.compile(r"(?:https?://)?learn\.microsoft\.com/(\S+)", re.IGNORECASE)
_HANDLE = re.compile(r"^((?:corpus|topic)-synthesis-[A-Za-z0-9_.-]+)$")
_SAME_SOURCE = re.compile(r"^same source$", re.IGNORECASE)
_GAP_PREFIX = re.compile(r"^G:\s*(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_NUMBERED = re.compile(r"^\d+\.\s+(.+)$")
_BARE_URL = re.compile(r"https?://[^\s<>\[\]()]+", re.IGNORECASE)
_TABLE_RULE = re.compile(r"^:?-{3,}:?$")
_STRENGTH_MARK = re.compile(r"\[(?:C|S|I|G)\]")


@dataclass(frozen=True)
class SynthesisSource:
    """One numbered source in a synthesis reading copy."""

    number: int
    title: str
    kind: str
    locator: str
    url: str


@dataclass(frozen=True)
class ReadingSynthesis:
    """Markdown body with citation tokens, plus the numbered source list."""

    title: str
    body: str
    sources: tuple[SynthesisSource, ...]
    has_strength_labels: bool


class _Draft:
    def __init__(self, number: int, title: str, kind: str, locator: str, url: str) -> None:
        self.number = number
        self.title = title
        self.kind = kind
        self.locator = locator
        self.url = url


class _CitationState:
    def __init__(self) -> None:
        self.sources: list[_Draft] = []
        self.by_key: dict[str, _Draft] = {}
        self.by_title: dict[str, _Draft] = {}
        self.last: int | None = None

    def add(self, text: str) -> int:
        key, title, kind, locator, url = _describe_citation(text)
        title_key = _norm_title(title) if title else ""
        found = self.by_key.get(key)
        if found is None and title_key:
            found = self.by_title.get(title_key)
        if found is None:
            found = _Draft(
                number=len(self.sources) + 1,
                title=title,
                kind=kind,
                locator=locator,
                url=url,
            )
            self.sources.append(found)
        else:
            _merge_source(found, title, kind, locator, url)
        self.by_key[key] = found
        if found.title:
            self.by_title[_norm_title(found.title)] = found
        self.last = found.number
        return found.number

    def add_link(self, label: str, url: str) -> int:
        cleaned_url = url.strip()
        number = self.add(cleaned_url)
        found = self.sources[number - 1]
        if cleaned_url and not found.url:
            found.url = cleaned_url
        if found.kind == "Source":
            found.kind = "Web page"
        cleaned = label.strip()
        title_is_url = bool(found.title) and found.title.casefold() == cleaned_url.casefold()
        if cleaned and cleaned.casefold() != cleaned_url.casefold():
            if not found.title or title_is_url:
                found.title = cleaned
                self.by_title[_norm_title(cleaned)] = found
        elif title_is_url:
            found.title = ""
        return number


def prepare_reading_synthesis(
    markdown: str,
    *,
    title: str | None = None,
    fallback_name: str = "synthesis",
) -> ReadingSynthesis:
    """Number bracketed sources and lift them out of the prose."""

    body, drafts = _rewrite_citations(markdown)
    sources = tuple(
        SynthesisSource(
            number=draft.number,
            title=draft.title,
            kind=draft.kind,
            locator=draft.locator,
            url=draft.url,
        )
        for draft in drafts
    )
    return ReadingSynthesis(
        title=_document_title(markdown, title, fallback_name),
        body=body,
        sources=sources,
        has_strength_labels=_STRENGTH_MARK.search(body) is not None,
    )


def write_synthesis_document(
    markdown: str,
    docx_path: Path,
    *,
    title: str | None = None,
) -> Path:
    """Write a Word reading copy of ``markdown`` to ``docx_path``."""

    reading = prepare_reading_synthesis(markdown, title=title, fallback_name=docx_path.stem)
    document = new_document()
    _setup_styles(document)
    _add_cover(document, reading)
    body_section = document.add_section(WD_SECTION.NEW_PAGE)
    _apply_page(document.sections[0])
    _apply_page(body_section)
    for section in document.sections:
        section.header.is_linked_to_previous = False
        section.footer.is_linked_to_previous = False
    _add_header(body_section, reading.title)
    _add_page_number(body_section)
    _restart_page_numbers(body_section)
    headings = _section_headings(reading.body)
    bibliography = (
        "Works cited" if any(item.casefold() == "sources" for item in headings) else "Sources"
    )
    if reading.has_strength_labels:
        _add_strength_note(document)
    _render_body(document, reading.body)
    _add_sources(document, reading.sources, bibliography)
    _save(document, docx_path)
    return docx_path


def _rewrite_citations(markdown: str) -> tuple[str, list[_Draft]]:
    state = _CitationState()
    output: list[str] = []
    index = 0
    in_code = False
    while index < len(markdown):
        if markdown.startswith("```", index):
            in_code = not in_code
            output.append("```")
            index += 3
            continue
        if not in_code:
            linked = _read_bare_url(markdown, index, state)
            if linked is not None:
                chunk, index = linked
                if output and output[-1].endswith(" "):
                    output[-1] = output[-1][:-1]
                output.append(chunk)
                continue
        if in_code or markdown[index] != "[":
            chunk, index = _copy_plain(markdown, index, in_code=in_code)
            output.append(chunk)
            continue
        chunk, index, trim = _read_bracket(markdown, index, state)
        if trim and output and output[-1].endswith(" "):
            output[-1] = output[-1][:-1]
        output.append(chunk)
    return "".join(output), state.sources


def _copy_plain(markdown: str, index: int, *, in_code: bool) -> tuple[str, int]:
    if in_code or markdown[index] != "`":
        return markdown[index], index + 1
    closing = markdown.find("`", index + 1)
    if closing == -1 or "\n" in markdown[index:closing]:
        return markdown[index], index + 1
    return markdown[index : closing + 1], closing + 1


def _read_bracket(markdown: str, index: int, state: _CitationState) -> tuple[str, int, bool]:
    if index > 0 and markdown[index - 1].isalnum():
        return "[", index + 1, False
    closing = _bracket_end(markdown, index)
    if closing is None:
        return "[", index + 1, False
    linked = _read_markdown_link(markdown, index, closing, state)
    if linked is not None:
        return linked
    replacement = _replace_bracket(markdown[index + 1 : closing], state)
    if replacement is None:
        return markdown[index : closing + 1], closing + 1, False
    return replacement, closing + 1, replacement.startswith("{{cite:")


def _read_bare_url(markdown: str, index: int, state: _CitationState) -> tuple[str, int] | None:
    match = _BARE_URL.match(markdown, index)
    if match is None:
        return None
    url = match.group(0).rstrip(".,;:!?")
    return f"{{{{cite:{state.add_link('', url)}}}}}", index + len(url)


def _read_markdown_link(
    markdown: str,
    index: int,
    closing: int,
    state: _CitationState,
) -> tuple[str, int, bool] | None:
    if closing + 1 >= len(markdown) or markdown[closing + 1] != "(":
        return None
    url_end = markdown.find(")", closing + 2)
    if url_end == -1 or "\n" in markdown[closing + 2 : url_end]:
        return None
    url = markdown[closing + 2 : url_end].strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    label = markdown[index + 1 : closing].strip()
    token = f"{{{{cite:{state.add_link(label, url)}}}}}"
    if not label:
        return token, url_end + 1, True
    return f"{label}{token}", url_end + 1, False


def _bracket_end(markdown: str, index: int) -> int | None:
    closing = markdown.find("]", index + 1)
    if closing == -1 or "\n" in markdown[index + 1 : closing] or closing - index > 400:
        return None
    return closing


def _replace_bracket(inner: str, state: _CitationState) -> str | None:
    if re.fullmatch(r"[a-z]", inner.strip()):
        return None
    parts = [part.strip() for part in inner.split(";") if part.strip()]
    if len(parts) == 1 and parts[0] in _STRENGTH | _BADGES:
        return None
    strength, numbers = _collect_citation_numbers(parts, state)
    if not numbers:
        return None
    token = "{{cite:" + ",".join(str(number) for number in numbers) + "}}"
    return f"{strength}{token}" if strength else token


def _collect_citation_numbers(parts: list[str], state: _CitationState) -> tuple[str, list[int]]:
    strength = ""
    numbers: list[int] = []
    seen: set[int] = set()
    recognized = False
    for part in parts:
        part_strength, number, counted = _part_citation(part, state)
        recognized = recognized or counted
        if part_strength:
            strength = part_strength
        if number is not None and number not in seen:
            seen.add(number)
            numbers.append(number)
    if not recognized:
        return "", []
    return strength, numbers


def _part_citation(part: str, state: _CitationState) -> tuple[str, int | None, bool]:
    if part in _STRENGTH or part in _BADGES:
        return f"[{part}]", None, True
    gap = _GAP_PREFIX.match(part)
    if gap:
        return _gap_citation(gap.group(1).strip(), state)
    if _SAME_SOURCE.match(part):
        return "", state.last, True
    if re.fullmatch(r"[a-z]", part):
        return "", None, False
    return "", state.add(part), True


def _gap_citation(remainder: str, state: _CitationState) -> tuple[str, int | None, bool]:
    if not remainder:
        return "[G]", None, True
    if _SAME_SOURCE.match(remainder):
        return "[G]", state.last, True
    return "[G]", state.add(remainder), True


def _describe_citation(text: str) -> tuple[str, str, str, str, str]:
    title, locator = _split_title_locator(text.strip())
    body = locator or text.strip()
    youtube = _YT_ID.search(body) or _YT_ID.search(text)
    if youtube:
        video_id = youtube.group(1)
        url = f"https://www.youtube.com/watch?v={video_id}"
        return f"yt:{video_id}", title, "Video", f"YouTube {video_id}", url
    arxiv = _ARXIV_URL.search(text) or _ARXIV_LABEL.search(text)
    if arxiv is not None:
        paper_id = arxiv.group(1)
        url = f"https://arxiv.org/abs/{paper_id}"
        return f"arxiv:{paper_id}", title, "Paper", f"arXiv {paper_id}", url
    learn = _LEARN.search(body) or _LEARN.search(text)
    if learn:
        path = learn.group(1).rstrip(".,);\"'")
        url = f"https://learn.microsoft.com/{path}"
        return f"learn:{path.casefold()}", title, "Documentation", url, url
    handle = _HANDLE.match(text.strip())
    if handle:
        name = handle.group(1)
        kind = "Corpus synthesis" if name.startswith("corpus-") else "Topic synthesis"
        slug = name.split("-synthesis-", 1)[1].replace("-", " ")
        return f"handle:{name}", f"{kind} for {slug}", kind, name, ""
    shown = text.strip()
    return f"title:{_norm_title(shown)}", shown, "Source", "", ""


def _prefer_title(current: str, incoming: str) -> bool:
    if not current:
        return True
    current_is_url = current.lower().startswith(("http://", "https://"))
    incoming_is_url = incoming.lower().startswith(("http://", "https://"))
    if incoming_is_url and not current_is_url:
        return False
    return current_is_url or len(incoming) > len(current)


def _split_title_locator(text: str) -> tuple[str, str]:
    for separator in _SEPARATORS:
        if separator not in text:
            continue
        left, right = text.split(separator, 1)
        if _looks_like_locator(right):
            return left.strip(), right.strip()
    return "", text.strip()


def _looks_like_locator(text: str) -> bool:
    sample = text.strip()
    return bool(
        _YT_ID.search(sample)
        or _ARXIV_URL.search(sample)
        or _ARXIV_LABEL.search(sample)
        or _LEARN.search(sample)
        or sample.lower().startswith(("http://", "https://"))
    )


def _merge_source(found: _Draft, title: str, kind: str, locator: str, url: str) -> None:
    if title and _prefer_title(found.title, title):
        found.title = title
    if url and not found.url:
        found.url = url
    if locator and not found.locator:
        found.locator = locator
    if kind != "Source" and found.kind == "Source":
        found.kind = kind


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().casefold()


def _document_title(markdown: str, explicit: str | None, fallback_name: str) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    for line in markdown.splitlines():
        if line.startswith("# ") and not line.startswith("##"):
            heading = line[2:].strip()
            if heading:
                return heading
    return _title_from_filename(fallback_name)


def _title_from_filename(name: str) -> str:
    stem = name[len("synthesis-") :] if name.lower().startswith("synthesis-") else name
    words = [word for word in stem.replace("_", "-").split("-") if word]
    if not words:
        return "Synthesis"
    return " ".join(word[:1].upper() + word[1:] if word.islower() else word for word in words)


def _setup_styles(document: DocxDocument) -> None:
    normal = _style(document, "Normal")
    if normal is not None:
        normal.font.name = "Aptos"
        normal.font.size = Pt(11)
        normal.font.color.rgb = _INK
        normal.paragraph_format.space_after = Pt(8)
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.line_spacing = 1.15
    for level, size in ((1, 18), (2, 14), (3, 12), (4, 11)):
        style = _style(document, f"Heading {level}")
        if style is None:
            continue
        style.font.name = "Aptos"
        style.font.size = Pt(size)
        style.font.color.rgb = _NAVY
        style.font.bold = True
        style.paragraph_format.space_before = Pt(16 if level == 1 else 12)
        style.paragraph_format.space_after = Pt(4)


def _style(document: DocxDocument, name: str) -> ParagraphStyle | None:
    if name not in document.styles:
        return None
    style = document.styles[name]
    if isinstance(style, ParagraphStyle):
        return style
    return None


def _apply_page(section: Section) -> None:
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.9)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.9)
    section.right_margin = Inches(0.9)
    section.header_distance = Inches(0.35)
    section.footer_distance = Inches(0.35)


def _add_cover(document: DocxDocument, reading: ReadingSynthesis) -> None:
    kicker = document.add_paragraph()
    kicker.alignment = WD_ALIGN_PARAGRAPH.CENTER
    kicker.paragraph_format.space_before = Pt(72)
    kicker.paragraph_format.space_after = Pt(10)
    run = kicker.add_run("Distill synthesis")
    run.font.name = "Aptos"
    run.font.size = Pt(11)
    run.font.color.rgb = _ACCENT
    run.font.all_caps = True
    run.bold = True

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(8)
    run = title.add_run(reading.title)
    run.font.name = "Aptos"
    run.font.size = Pt(28)
    run.font.color.rgb = _NAVY
    run.bold = True
    _bottom_border(title, "1F4E79")

    summary = document.add_paragraph()
    summary.alignment = WD_ALIGN_PARAGRAPH.CENTER
    summary.paragraph_format.space_before = Pt(14)
    _muted(
        summary,
        "Reading copy. Citation numbers in the text point to the source list at the end.",
    )
    count = document.add_paragraph()
    count.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _muted(count, _source_count(len(reading.sources)))
    rendered = document.add_paragraph()
    rendered.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rendered.paragraph_format.space_before = Pt(18)
    now = datetime.now()
    _muted(rendered, f"Rendered {now:%B} {now.day}, {now:%Y}")


def _source_count(count: int) -> str:
    if count == 0:
        return "No bracketed sources in this synthesis."
    if count == 1:
        return "1 source, numbered at first use."
    return f"{count} sources, numbered at first use."


def _add_header(section: Section, title: str) -> None:
    header = section.header
    paragraph = header.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    shown = title if len(title) <= 80 else title[:77] + "..."
    run = paragraph.add_run(shown)
    run.font.name = "Aptos"
    run.font.size = Pt(9)
    run.font.color.rgb = _MUTED
    _bottom_border(paragraph, _RULE)


def _add_page_number(section: Section) -> None:
    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_field(paragraph, " PAGE ")
    for run in paragraph.runs:
        run.font.name = "Aptos"
        run.font.size = Pt(9)
        run.font.color.rgb = _MUTED


def _add_field(paragraph: Paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run._r.append(begin)
    text = OxmlElement("w:instrText")
    text.set(qn("xml:space"), "preserve")
    text.text = instruction
    run._r.append(text)
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(end)


def _restart_page_numbers(section: Section) -> None:
    sect_pr = section._sectPr
    numbering = OxmlElement("w:pgNumType")
    numbering.set(qn("w:start"), "1")
    sect_pr.append(numbering)


def _section_headings(body: str) -> list[str]:
    top = _top_heading_level(body)
    headings: list[str] = []
    for line in body.splitlines():
        parsed = _HEADING.match(line.strip())
        if parsed is None or len(parsed.group(1)) != top:
            continue
        title = parsed.group(2).strip()
        if title.casefold() not in {"contents", "table of contents"}:
            headings.append(title)
    return headings


def _top_heading_level(body: str) -> int:
    levels = [
        len(match.group(1))
        for line in body.splitlines()
        if (match := _HEADING.match(line.strip())) is not None
    ]
    return min(levels) if levels else 2


def _add_strength_note(document: DocxDocument) -> None:
    note = document.add_paragraph()
    note.paragraph_format.space_before = Pt(10)
    _muted(
        note,
        "Labels [C], [S], [I], and [G] mark claim strength. They are not source numbers. "
        "Superscript numbers list the sources at the end.",
    )


def _render_body(document: DocxDocument, body: str) -> None:
    lines = body.split("\n")
    top = _top_heading_level(body)
    index = 0
    while index < len(lines):
        index = _render_block(document, lines, index, top)


def _render_block(document: DocxDocument, lines: list[str], index: int, top: int) -> int:
    stripped = lines[index].strip()
    if stripped.startswith("```"):
        return _render_fence(document, lines, index)
    if _table_starts(lines, index):
        return _render_table(document, lines, index)
    if not stripped:
        return index + 1
    if _render_heading(document, stripped, top):
        return index + 1
    if stripped in {"---", "***", "___"}:
        _add_rule(document)
        return index + 1
    if _render_list_item(document, stripped):
        return index + 1
    return _render_paragraph(document, lines, index)


def _render_fence(document: DocxDocument, lines: list[str], index: int) -> int:
    index += 1
    collected: list[str] = []
    while index < len(lines) and not lines[index].strip().startswith("```"):
        collected.append(lines[index])
        index += 1
    if index < len(lines):
        index += 1
    _add_code(document, "\n".join(collected))
    return index


def _render_heading(document: DocxDocument, stripped: str, top: int) -> bool:
    heading = _HEADING.match(stripped)
    if heading is None:
        return False
    level = min(len(heading.group(1)) - top + 1, 4)
    document.add_heading(heading.group(2).strip(), level=max(level, 1))
    return True


def _add_rule(document: DocxDocument) -> None:
    rule = document.add_paragraph()
    rule.paragraph_format.space_before = Pt(4)
    rule.paragraph_format.space_after = Pt(4)
    _bottom_border(rule, _RULE)


def _render_list_item(document: DocxDocument, stripped: str) -> bool:
    if stripped.startswith("- ") or stripped.startswith("* "):
        paragraph = document.add_paragraph(style="List Bullet")
        _add_inline(paragraph, stripped[2:].strip())
        return True
    numbered = _NUMBERED.match(stripped)
    if numbered is None:
        return False
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.5)
    paragraph.paragraph_format.first_line_indent = Inches(-0.5)
    paragraph.paragraph_format.space_after = Pt(4)
    _add_inline(paragraph, stripped)
    return True


def _render_paragraph(document: DocxDocument, lines: list[str], index: int) -> int:
    collected = lines[index].strip()
    index += 1
    while index < len(lines) and lines[index].strip() and not _structural_line(lines, index):
        collected += " " + lines[index].strip()
        index += 1
    paragraph = document.add_paragraph()
    _add_inline(paragraph, collected)
    return index


def _structural_line(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip()
    return bool(
        not stripped
        or stripped.startswith("#")
        or stripped.startswith("```")
        or stripped.startswith("- ")
        or stripped.startswith("* ")
        or stripped in {"---", "***", "___"}
        or _NUMBERED.match(stripped)
        or _table_starts(lines, index)
    )


def _table_starts(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines) or "|" not in lines[index]:
        return False
    return _is_table_rule(lines[index + 1])


def _is_table_rule(line: str) -> bool:
    text = line.strip()
    if not text.startswith("|"):
        return False
    cells = [cell.strip() for cell in text.strip("|").split("|")]
    return bool(cells) and all(_TABLE_RULE.fullmatch(cell) for cell in cells)


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_table(document: DocxDocument, lines: list[str], index: int) -> int:
    rows = [_split_row(lines[index])]
    index += 2
    while index < len(lines) and lines[index].strip().startswith("|"):
        if _is_table_rule(lines[index]):
            break
        rows.append(_split_row(lines[index]))
        index += 1
    columns = max(len(row) for row in rows)
    padded = [row + [""] * (columns - len(row)) for row in rows]
    table = document.add_table(rows=len(padded), cols=columns)
    table.style = "Table Grid"
    table.autofit = True
    _format_table(table)
    for row_index, row in enumerate(padded):
        for column, text in enumerate(row):
            cell = table.cell(row_index, column)
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(2)
            _add_inline(paragraph, text, size=10)
            if row_index == 0:
                _shade(cell, _HEADER_FILL)
                for run in paragraph.runs:
                    run.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    run.font.size = Pt(10)
            elif row_index % 2 == 0:
                _shade(cell, _BAND)
    _mark_header_row(table)
    document.add_paragraph().paragraph_format.space_after = Pt(6)
    return index


def _format_table(table: Table) -> None:
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    if tbl_pr is None:
        return
    # 6.7 in is the body text width. Word lays pct widths out 8 pt wider once
    # the cell margins below are included, so the table is set in twips.
    width = OxmlElement("w:tblW")
    width.set(qn("w:w"), "9648")
    width.set(qn("w:type"), "dxa")
    tbl_pr.append(width)
    margins = OxmlElement("w:tblCellMar")
    for edge, value in (("top", "60"), ("left", "80"), ("bottom", "60"), ("right", "80")):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:w"), value)
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    tbl_pr.append(margins)


def _shade(cell: _Cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def _mark_header_row(table: Table) -> None:
    properties = table.rows[0]._tr.get_or_add_trPr()
    marker = OxmlElement("w:tblHeader")
    properties.append(marker)


def _add_sources(
    document: DocxDocument, sources: tuple[SynthesisSource, ...], heading: str
) -> None:
    document.add_heading(heading, level=1)
    intro = document.add_paragraph()
    _add_inline(
        intro,
        "Sources are numbered in the order they first appear. A repeated source keeps its "
        "number. Corpus and topic syntheses are derived local artifacts, not external publications.",
    )
    if not sources:
        empty = document.add_paragraph()
        _muted(empty, "This synthesis has no bracketed source citations to list.")
        return
    for source in sources:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.4)
        paragraph.paragraph_format.first_line_indent = Inches(-0.4)
        paragraph.paragraph_format.space_after = Pt(8)
        _add_inline(paragraph, f"{source.number}. {_source_label(source)}")
        if source.url:
            paragraph.add_run(" ")
            _add_hyperlink(paragraph, source.url, source.url)


def _source_label(source: SynthesisSource) -> str:
    if source.kind.endswith("synthesis"):
        return f"{source.title or source.kind}. Derived local artifact"
    label = source.title or source.locator or source.kind
    details: list[str] = []
    if source.kind and source.kind not in label:
        details.append(source.kind)
    if source.locator and source.locator not in label and source.locator != source.url:
        details.append(source.locator)
    if not details:
        return label
    return f"{label}. {'. '.join(details)}"


def _add_code(document: DocxDocument, code: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(8)
    run = paragraph.add_run(code)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    run.font.color.rgb = _INK
    _shade_paragraph(paragraph, "F7F8FA")


def _shade_paragraph(paragraph: Paragraph, fill: str) -> None:
    properties = paragraph._p.get_or_add_pPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def _add_inline(
    paragraph: Paragraph, text: str, *, size: int = 11, base_bold: bool = False
) -> None:
    bold = base_bold
    italic = False
    plain: list[str] = []
    index = 0

    def flush() -> None:
        if not plain:
            return
        run = paragraph.add_run("".join(plain))
        run.bold = bold or None
        run.italic = italic or None
        run.font.name = "Aptos"
        run.font.size = Pt(size)
        run.font.color.rgb = _INK
        plain.clear()

    while index < len(text):
        marker = _markup_span(text, index)
        if marker is None:
            plain.append(text[index])
            index += 1
            continue
        flush()
        kind, end, payload = marker
        if kind == "cite":
            _add_citation_runs(paragraph, payload.split(","), size=size, bold=bold)
        elif kind == "bold":
            bold = not bold
        elif kind == "italic":
            italic = not italic
        elif kind == "code":
            run = paragraph.add_run(payload)
            run.font.name = "Consolas"
            run.font.size = Pt(max(size - 1, 8))
            run.bold = bold or None
        else:
            label, _url = payload.split("\n", 1)
            plain.append(label)
            flush()
        index = end
    flush()


def _markup_span(text: str, index: int) -> tuple[str, int, str] | None:
    if text.startswith("{{cite:", index):
        closing = text.find("}}", index)
        if closing != -1:
            return "cite", closing + 2, text[index + 7 : closing]
    if text.startswith("**", index):
        return "bold", index + 2, ""
    code = _code_span(text, index)
    if code is not None:
        return code
    link = _link_span(text, index)
    if link is not None:
        return link
    return _italic_span(text, index)


def _code_span(text: str, index: int) -> tuple[str, int, str] | None:
    if not text.startswith("`", index):
        return None
    closing = text.find("`", index + 1)
    if closing == -1:
        return None
    return "code", closing + 1, text[index + 1 : closing]


def _link_span(text: str, index: int) -> tuple[str, int, str] | None:
    if text[index] != "[":
        return None
    label_end = text.find("]", index + 1)
    if label_end == -1 or not text.startswith("](", label_end):
        return None
    url_end = text.find(")", label_end + 2)
    if url_end == -1:
        return None
    label = text[index + 1 : label_end]
    url = text[label_end + 2 : url_end]
    return "link", url_end + 1, f"{label}\n{url}"


def _italic_span(text: str, index: int) -> tuple[str, int, str] | None:
    if text[index] != "*" or text.startswith("**", index):
        return None
    closing = text.find("*", index + 1)
    if closing == -1 or "\n" in text[index:closing] or closing - index > 240:
        return None
    return "italic", index + 1, ""


def _add_citation_runs(paragraph: Paragraph, numbers: list[str], *, size: int, bold: bool) -> None:
    for position, number in enumerate(numbers):
        if position:
            comma = paragraph.add_run(",")
            comma.font.superscript = True
            comma.font.size = Pt(max(size - 3, 8))
            comma.font.name = "Aptos"
            comma.font.color.rgb = _ACCENT
            comma.bold = bold or None
        run = paragraph.add_run(number)
        run.font.superscript = True
        run.font.size = Pt(max(size - 2, 8))
        run.font.color.rgb = _ACCENT
        run.font.name = "Aptos"
        run.bold = True


def _add_hyperlink(paragraph: Paragraph, text: str, url: str) -> None:
    relation = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relation)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1F4E79")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "21")
    properties.extend((color, underline, size))
    run.append(properties)
    node = OxmlElement("w:t")
    node.set(qn("xml:space"), "preserve")
    node.text = text
    run.append(node)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _muted(paragraph: Paragraph, text: str) -> None:
    run = paragraph.add_run(text)
    run.font.name = "Aptos"
    run.font.size = Pt(11)
    run.font.color.rgb = _MUTED
    run.italic = True


def _bottom_border(paragraph: Paragraph, color: str) -> None:
    properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    properties.append(borders)


def _save(document: DocxDocument, docx_path: Path) -> None:
    buffer = BytesIO()
    document.save(buffer)
    atomic_write_bytes(docx_path, buffer.getvalue())
