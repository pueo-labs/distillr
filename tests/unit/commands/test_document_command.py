"""CLI coverage for distill document."""

from pathlib import Path

from typer.testing import CliRunner

from distill import cli

runner = CliRunner()


def test_document_renders_an_existing_synthesis(tmp_path: Path) -> None:
    source = tmp_path / "synthesis-demo.md"
    source.write_text("# Demo\n\nA claim [YT abcdefghi].\n", encoding="utf-8")
    output = tmp_path / "reading.docx"

    result = runner.invoke(
        cli.app, ["document", str(source), "--output", str(output), "--title", "Demo"]
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert "Reading copy:" in result.output
    assert source.read_text(encoding="utf-8").startswith("# Demo")


def test_document_refuses_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    result = runner.invoke(cli.app, ["document", str(missing)])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_document_refuses_an_empty_file(tmp_path: Path) -> None:
    source = tmp_path / "empty.md"
    source.write_text("  \n", encoding="utf-8")
    result = runner.invoke(cli.app, ["document", str(source)])
    assert result.exit_code == 1
    assert "empty" in result.output


def test_document_refuses_remote_paths_and_a_non_docx_name(tmp_path: Path) -> None:
    source = tmp_path / "note.md"
    source.write_text("# Note\n\nBody.\n", encoding="utf-8")

    remote_source = runner.invoke(cli.app, ["document", r"\\server\share\file.md"])
    assert remote_source.exit_code == 1
    assert "remote" in remote_source.output

    remote_output = runner.invoke(
        cli.app,
        ["document", str(source), "--output", r"\\server\share\out.docx"],
    )
    assert remote_output.exit_code == 1
    assert "remote" in remote_output.output

    bad_suffix = runner.invoke(
        cli.app, ["document", str(source), "--output", str(tmp_path / "note.txt")]
    )
    assert bad_suffix.exit_code == 1
    assert ".docx" in bad_suffix.output


def test_document_refuses_text_that_is_not_utf8(tmp_path: Path) -> None:
    source = tmp_path / "bad.md"
    source.write_bytes(b"\xff\xfe not utf8")
    result = runner.invoke(cli.app, ["document", str(source)])
    assert result.exit_code == 1
    assert "UTF-8" in result.output


def test_document_refuses_a_word_source(tmp_path: Path) -> None:
    source = tmp_path / "already.docx"
    source.write_bytes(b"not a real docx")
    result = runner.invoke(cli.app, ["document", str(source)])
    assert result.exit_code == 1
    assert "Markdown" in result.output
