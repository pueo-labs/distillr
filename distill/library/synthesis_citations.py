"""Number bracketed sources for a synthesis reading copy.

The Markdown synthesis stays unchanged. This module turns brackets, Markdown
links, and bare URLs into citation tokens and one numbered source list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ReadingSynthesis",
    "SynthesisSource",
    "prepare_reading_synthesis",
]

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
_BARE_URL = re.compile(r"https?://[^\s<>\[\]()]+", re.IGNORECASE)
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
