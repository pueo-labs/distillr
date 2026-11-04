"""Reading-copy synthesis documents: numbered sources, tables, and Word layout."""

import zipfile
from pathlib import Path

from docx import Document

from distill.library.synthesis_document import (
    prepare_reading_synthesis,
    write_synthesis_document,
)

_SAMPLE = """## 1. Thesis

ShareTech states the split [How Microsoft Agent 365 Actually Works Under the Hood \u2014 YT Jv9U3LROXEA].
Mechanics agrees [YT yWwYLbMvc3s; YT Jv9U3LROXEA]. **[C]**

The docs agree [Microsoft Purview data security solutions]. **[S]**
Later the URL form appears [Microsoft Purview data security solutions - learn.microsoft.com/en-us/purview/purview-security].

- "SDK sample" [same source]. **[S]**
- Gap note [G: YT Jv9U3LROXEA]
- Keep [the page](https://example.com/keep) and block[s] the action.
- Badge stays [Confirmed].

`[YT Jv9U3LROXEA]`

```
[YT Jv9U3LROXEA]
```

| Plane | Evidence |
| --- | --- |
| **Control** | [YT Jv9U3LROXEA] |
| Execution | [corpus-synthesis-agent365] |

Derived [topic-synthesis-agent365] and [Bono \u2014 arXiv 2401.01234].
See https://example.com/bare-note.
See [note](not-a-url).
Again [Purview](https://learn.microsoft.com/en-us/purview/purview-security) and [](https://example.com/keep).
"""


def test_prepare_numbers_sources_once_and_keeps_strength_labels() -> None:
    reading = prepare_reading_synthesis(_SAMPLE, title="Agent 365")

    assert reading.title == "Agent 365"
    assert reading.has_strength_labels is True
    assert [source.number for source in reading.sources[:8]] == [1, 2, 3, 4, 5, 6, 7, 8]
    sharetech, mechanics, purview, page, corpus, topic, paper, bare = reading.sources[:8]
    assert sharetech.kind == "Video"
    assert sharetech.url == "https://www.youtube.com/watch?v=Jv9U3LROXEA"
    assert "Under the Hood" in sharetech.title
    assert mechanics.url.endswith("yWwYLbMvc3s")
    assert purview.kind == "Documentation"
    assert purview.url == "https://learn.microsoft.com/en-us/purview/purview-security"
    assert page.title == "the page"
    assert page.url == "https://example.com/keep"
    assert page.kind == "Web page"
    assert corpus.kind == "Corpus synthesis"
    assert topic.kind == "Topic synthesis"
    assert paper.kind == "Paper"
    assert paper.url == "https://arxiv.org/abs/2401.01234"
    assert bare.title == ""
    assert bare.url == "https://example.com/bare-note"
    assert reading.sources[8].title == "note"
    assert purview.title == "Microsoft Purview data security solutions"
    assert "the page{{cite:4}}" in reading.body
    assert "See{{cite:8}}" in reading.body
    assert "Again Purview{{cite:3}}" in reading.body
    assert "and{{cite:4}}" in reading.body
    assert "https://example.com/keep" not in reading.body
    assert "https://example.com/bare-note" not in reading.body
    assert "{{cite:2,1}}" in reading.body
    assert "[G]{{cite:1}}" in reading.body
    assert "**[C]**" in reading.body
    assert "[same source]" not in reading.body
    assert "block[s]" in reading.body
    assert "`[YT Jv9U3LROXEA]`" in reading.body
    assert "```\n[YT Jv9U3LROXEA]\n```" in reading.body


def test_one_source_uses_the_singular_cover_line(tmp_path: Path) -> None:
    output = tmp_path / "one.docx"
    write_synthesis_document("Only [YT abcdefghi].", output, title="One")

    text = "\n".join(paragraph.text for paragraph in Document(output).paragraphs)
    assert "1 source, numbered at first use." in text


def test_filename_title_when_the_synthesis_has_no_h1() -> None:
    reading = prepare_reading_synthesis(
        "## Only\n\nNo citation.", fallback_name="synthesis-agent365-meta-paper"
    )

    assert reading.title == "Agent365 Meta Paper"
    assert reading.sources == ()


def test_write_synthesis_document_lays_out_sources_tables_and_page_numbers(tmp_path: Path) -> None:
    output = tmp_path / "synthesis-agent365.docx"
    write_synthesis_document(_SAMPLE, output, title="Agent 365")

    document = Document(output)
    plain = _visible_text(document)
    assert "Agent 365" in plain
    assert "Reading copy." in plain
    assert "9 sources, numbered at first use." in plain
    assert "Contents" not in plain
    assert "https://example.com/keep" not in plain
    assert "https://example.com/bare-note" not in plain
    assert "Labels [C], [S], [I], and [G] mark claim strength." in plain
    assert "same source" not in plain
    assert "block[s] the action." in plain
    assert "YT Jv9U3LROXEA" not in plain
    assert document.tables
    header = document.tables[0].rows[0].cells[0].text
    evidence = document.tables[0].rows[1].cells[1].text
    assert header == "Plane"
    assert "YT" not in evidence
    assert any(
        run.font.superscript for run in document.tables[0].rows[1].cells[1].paragraphs[0].runs
    )
    assert document.sections[1].header.paragraphs[0].text == "Agent 365"
    assert "Corpus synthesis for agent365. Derived local artifact" in plain
    assert "topic-synthesis-agent365" not in plain

    package = zipfile.ZipFile(output)
    document_xml = package.read("word/document.xml").decode("utf-8")
    assert "https://www.youtube.com/watch?v=Jv9U3LROXEA" in document_xml
    assert "https://learn.microsoft.com/en-us/purview/purview-security" in document_xml
    assert "https://arxiv.org/abs/2401.01234" in document_xml
    assert "https://example.com/keep" in document_xml
    assert "https://example.com/bare-note" in document_xml
    assert "w:tblHeader" in document_xml
    assert 'w:w="9648"' in document_xml
    footers = [name for name in package.namelist() if name.startswith("word/footer")]
    assert any("PAGE" in package.read(name).decode("utf-8") for name in footers)


def test_empty_citation_synthesis_still_writes_a_document(tmp_path: Path) -> None:
    output = tmp_path / "plain.docx"
    write_synthesis_document("# Plain title\n\nNo sources here.", output)

    document = Document(output)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Plain title" in text
    assert "No bracketed sources" in text
    assert "Contents" not in text
    assert "This synthesis has no bracketed source citations to list." in text


def test_edge_citations_keep_authored_list_numbers_and_clean_contents(tmp_path: Path) -> None:
    markdown = _edge_markdown()
    reading = prepare_reading_synthesis(markdown)
    skipped = prepare_reading_synthesis("# \n\n# Kept Title\n")
    untitled = prepare_reading_synthesis("No heading.\n", fallback_name="synthesis-")

    assert skipped.title == "Kept Title"
    assert untitled.title == "Synthesis"
    assert "[s]" in reading.body
    assert "[a; b]" in reading.body
    assert "[G:]" in reading.body
    assert "[G]{{cite:2}}" in reading.body
    assert "{{cite:2,2}}" not in reading.body
    assert "[C]{{cite:2}}" in reading.body
    cost, sharetech, letter, video, docs = reading.sources[:5]
    link = next(source for source in reading.sources if source.url == "https://example.com/docs")
    assert cost.title == "Cost \u2014 benefit note"
    assert cost.kind == "Source"
    assert sharetech.title == "ShareTech walkthrough"
    assert sharetech.url.endswith("abcdefghi")
    assert letter.locator == "YouTube zzzzzzzzz"
    assert video.title == "Video notes"
    assert docs.title == "Platform Documentation"
    assert docs.locator == docs.url
    assert link.title == "the docs"
    assert "the docs{{cite:" in reading.body
    assert "https://example.com/docs" not in reading.body
    assert "x" * 40 in reading.body

    output = tmp_path / "edges.docx"
    write_synthesis_document(markdown, output)
    document = Document(output)
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert any(text == "1. First findings" for text in texts)
    assert any(text.startswith("1. Alpha point") for text in texts)
    assert any(text.startswith("1. Gamma point") for text in texts)
    assert texts.count("Contents") == 1
    assert any(text == "Works cited" for text in texts)
    assert all(
        paragraph.style is None or paragraph.style.name != "List Number"
        for paragraph in document.paragraphs
    )
    assert any(
        run.font.name == "Consolas" and "fence stays open" in run.text
        for paragraph in document.paragraphs
        for run in paragraph.runs
    )
    assert document.tables[0].rows[0].cells[0].text == "A"
    package = zipfile.ZipFile(output)
    assert "https://example.com/docs" in package.read("word/document.xml").decode("utf-8")


def test_long_titles_are_shortened_in_the_header(tmp_path: Path) -> None:
    title = "A" * 90
    output = tmp_path / "long.docx"
    write_synthesis_document("# Short\n\nBody.", output, title=title)

    header = Document(output).sections[1].header.paragraphs[0].text
    assert header == ("A" * 77) + "..."
    assert len(header) == 80


def test_missing_styles_and_unclosed_markup_are_safe() -> None:
    from types import SimpleNamespace
    from typing import cast

    from docx.styles.style import ParagraphStyle
    from docx.table import Table

    from distill.library.synthesis_document import (
        _add_inline,
        _format_table,
        _italic_span,
        _setup_styles,
        _style,
    )

    document = Document()
    assert _style(document, "Missing Style") is None
    character = next(style for style in document.styles if not isinstance(style, ParagraphStyle))
    assert _style(document, character.name) is None

    bare = Document()
    bare.styles.element.remove(bare.styles["Normal"].element)
    bare.styles.element.remove(bare.styles["Heading 4"].element)
    _setup_styles(bare)

    empty = Document()
    _format_table(cast(Table, SimpleNamespace(_tbl=SimpleNamespace(tblPr=None))))
    linked = empty.add_paragraph()
    _add_inline(linked, "Read [the docs](https://example.com/docs) now")
    assert linked.text == "Read the docs now"
    assert "https://" not in linked._p.xml

    paragraph = empty.add_paragraph()
    assert _italic_span("*open\nline*", 0) is None
    assert _italic_span("*" + ("a" * 241) + "*", 0) is None
    _add_inline(paragraph, "*kept* {{cite:1 `code [label](https://example.com")
    assert any(run.italic for run in paragraph.runs)


def _edge_markdown() -> str:
    lines = [
        "## Contents",
        "",
        "## 1. First findings",
        "",
        "`unclosed",
        "[also unclosed",
        "[" + ("x" * 410) + "]",
        "[s] [a; b] []",
        "A cost note [Cost \u2014 benefit note].",
        "Short first [YT abcdefghi].",
        "Longer later [ShareTech walkthrough \u2014 YT abcdefghi].",
        "Mixed [C; YT abcdefghi].",
        "Gap only [G:].",
        "Gap same [G: same source].",
        "Repeated [YT abcdefghi; YT abcdefghi].",
        "Letter [a; YT zzzzzzzzz].",
        "Video word [Video notes \u2014 YT qqqqqqqqq].",
        "Docs [Platform Documentation - learn.microsoft.com/en-us/purview/developer].",
        "Link [the docs](https://example.com/docs).",
        "Broken [broken](https://example.com",
        "Code `kept` and *italic words* and a star *",
        "{{cite:9",
        "see | pipe",
        "ordinary line",
        "",
        "---",
        "",
        "1. Alpha point",
        "2. Beta point",
        "",
        "Between.",
        "",
        "1. Gamma point",
        "",
        "| A | B |",
        "| --- | --- |",
        "| 1 | 2 |",
        "| --- | --- |",
        "",
        "```",
        "fence stays open",
        "",
        "## Sources",
        "",
    ]
    return "\n".join(lines)


def _visible_text(document: Document) -> str:
    chunks: list[str] = []
    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            if run.font.name != "Consolas":
                chunks.append(run.text)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        if run.font.name != "Consolas":
                            chunks.append(run.text)
    return "".join(chunks)
