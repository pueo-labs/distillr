"""Word reading copy of a synthesis.

The Markdown synthesis stays the inspectable record. Citation numbers come
from ``synthesis_citations``. This module renders the Word document:
superscript numbers in the prose, and each source listed once at the end.
"""

from __future__ import annotations

import re
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
from distill.library.synthesis_citations import (
    ReadingSynthesis,
    SynthesisSource,
    prepare_reading_synthesis,
)

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
_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_NUMBERED = re.compile(r"^\d+\.\s+(.+)$")
_TABLE_RULE = re.compile(r"^:?-{3,}:?$")


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
