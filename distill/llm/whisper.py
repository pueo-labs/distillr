"""OpenAI file-transcription client.

Lives under ``distill/llm/`` because the architectural test
``test_no_openai_construction_outside_llm`` enforces that direct
``OpenAI()`` construction stays in the LLM layer. Transcription is a
different OpenAI API surface than chat completions, but the same
client-construction discipline applies.

The ingestion layer (``distill/ingestors/transcribe.py``) imports and
calls :func:`transcribe_with_openai`; it does not construct the client
itself.
"""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI

__all__ = ["OPENAI_TRANSCRIPTION_MODEL", "transcribe_with_openai"]

# Current file-transcription model.
OPENAI_TRANSCRIPTION_MODEL = "gpt-transcribe"

_OPENAI_TRANSCRIPTION_MAX_BYTES = 25 * 1024 * 1024  # 25 MB upload cap per OpenAI's docs


def _transcription_text(result: object) -> str:
    """Normalize current text responses and legacy object-style responses."""
    if isinstance(result, str):
        return result
    response_text: object = getattr(result, "text", "")
    return str(response_text or result)


def transcribe_with_openai(
    media_path: Path,
    api_key: str,
    *,
    model: str = OPENAI_TRANSCRIPTION_MODEL,
    vocabulary_hint: str = "",
) -> str:
    """Transcribe *media_path* via ``POST /v1/audio/transcriptions``.

    ``vocabulary_hint`` becomes the ``prompt`` parameter, which supplies
    unstructured context such as proper nouns. The caller clips the hint.
    The request uses the model's default JSON response, whose ``text`` field
    is the transcript. ``response_format="text"`` is not sent: the documented
    ``gpt-transcribe`` result is a transcription object, and this helper still
    accepts a plain string from older responses.

    Raises :class:`ValueError` if *media_path* exceeds OpenAI's
    documented 25 MB upload cap, surfacing the limit upfront instead of
    waiting for the API's HTTP 413. Callers that need to handle longer
    audio should chunk the file or use ``distill.llm.grok_stt`` instead
    (Grok STT supports up to 500 MB per call).
    """
    from distill.llm.model_policy import superseded_replacement

    model = superseded_replacement(model)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    size_bytes = media_path.stat().st_size
    if size_bytes > _OPENAI_TRANSCRIPTION_MAX_BYTES:
        raise ValueError(
            f"OpenAI transcription rejects files larger than 25 MB; "
            f"{media_path.name} is {size_bytes / 1_000_000:.1f} MB. "
            "Use Grok STT (500 MB cap) or local faster-whisper instead."
        )

    client = OpenAI(api_key=api_key, max_retries=0)
    with media_path.open("rb") as fh:
        if vocabulary_hint:
            result = client.audio.transcriptions.create(
                file=fh,
                model=model,
                prompt=vocabulary_hint,
            )
        else:
            result = client.audio.transcriptions.create(
                file=fh,
                model=model,
            )
    return _transcription_text(result)
