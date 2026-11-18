# pyright: strict
"""Model capability policy helpers for provider routing."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)

XAI_MEDIA_GENERATION_MODEL_PREFIXES: tuple[str, ...] = (
    "grok-imagine-image",
    "grok-imagine-video",
)

RETIREMENT_DATE = "May 15, 2026"
RETIRED_MODELS: dict[str, str] = {
    "grok-4-1-fast-reasoning": "grok-4.7",
    "grok-4-1-fast-non-reasoning": "grok-4.7",
    "grok-4-fast-reasoning": "grok-4.7",
    "grok-4-fast-non-reasoning": "grok-4.7",
    "grok-4-0709": "grok-4.7",
    "grok-code-fast-1": "grok-4.7",
    "grok-3": "grok-4.7",
    "grok-imagine-image-pro": "grok-imagine-image-2.0",
}

# Configured ids that are no longer current. This is not the May 15, 2026
# retirement set. resolve() rewrites these before a call. The keys stay so an
# existing override cannot keep selecting a superseded model.
SUPERSEDED_MODELS: dict[str, str] = {
    "grok-4.6": "grok-4.7",
    "grok-4.5": "grok-4.7",
    "grok-4.3": "grok-4.7",
    "grok-4.20": "grok-4.7",
    "grok-4.20-multi-agent-0309": "grok-4.7",
    "grok-4.20-0309-non-reasoning": "grok-4.7",
    "grok-4.20-non-reasoning": "grok-4.7",
    "grok-4.20-0309-reasoning": "grok-4.7",
    "grok-imagine-image": "grok-imagine-image-2.0",
    "x-ai/grok-4.6": "x-ai/grok-4.7",
    "x-ai/grok-4.5": "x-ai/grok-4.7",
    "x-ai/grok-4.3": "x-ai/grok-4.7",
    "gemini-4-argon": "gemini-4-carbon",
    "gemini-3.7-flash": "gemini-3.8-flash",
    "gemini-3.6-flash": "gemini-3.8-flash",
    "gemini-3.5-flash": "gemini-3.8-flash",
    "gemini-3.1-flash": "gemini-3.8-flash",
    "gemini-3.1-pro": "gemini-4-carbon",
    "gemini-3.1-pro-preview": "gemini-4-carbon",
    "google/gemini-4-argon": "google/gemini-4-carbon",
    "google/gemini-3.7-flash": "google/gemini-3.8-flash",
    "google/gemini-3.6-flash": "google/gemini-3.8-flash",
    "google/gemini-3.5-flash": "google/gemini-3.8-flash",
    "google/gemini-3.1-pro": "google/gemini-4-carbon",
    "google/gemini-3.1-pro-preview": "google/gemini-4-carbon",
    "claude-sonnet-5": "claude-sonnet-5-5",
    "claude-sonnet-4": "claude-sonnet-5-5",
    "claude-opus-5": "claude-opus-5-5",
    "claude-opus-4": "claude-opus-5-5",
    "claude-opus-4-6": "claude-opus-5-5",
    "claude-opus-4-7": "claude-opus-5-5",
    "claude-opus-4-8": "claude-opus-5-5",
    "claude-fable-5": "claude-fable-5-2",
    "claude-fable-5-1": "claude-fable-5-2",
    "claude-fable-5.1": "claude-fable-5-2",
    "claude-mythos-5": "claude-mythos-5-2",
    "claude-mythos-5-1": "claude-mythos-5-2",
    "claude-mythos-5.1": "claude-mythos-5-2",
    "claude-haiku-4": "claude-haiku-5-5",
    "claude-haiku-4-5": "claude-haiku-5-5",
    "anthropic/claude-sonnet-5": "anthropic/claude-sonnet-5.5",
    "anthropic/claude-opus-5": "anthropic/claude-opus-5.5",
    "anthropic/claude-fable-5": "anthropic/claude-fable-5.2",
    "anthropic/claude-fable-5.1": "anthropic/claude-fable-5.2",
    "gpt-6-sol": "gpt-6.1-sol",
    "gpt-5.6": "gpt-6.1-sol",
    "gpt-5.6-sol": "gpt-6.1-sol",
    "gpt-5": "gpt-6.1-sol",
    "gpt-5.6-terra": "gpt-6.1-terra",
    "gpt-5-mini": "gpt-6.1-terra",
    "gpt-4.1": "gpt-6.1-terra",
    "gpt-4o": "gpt-6.1-terra",
    "gpt-5.6-luna": "gpt-6-luna",
    "gpt-5-nano": "gpt-6-luna",
    "gpt-4.1-mini": "gpt-6-luna",
    "gpt-4.1-nano": "gpt-6-luna",
    "gpt-4o-mini": "gpt-6-luna",
    "openai/gpt-6-sol": "openai/gpt-6.1-sol",
    "openai/gpt-5.6": "openai/gpt-6.1-sol",
    "openai/gpt-5.6-sol": "openai/gpt-6.1-sol",
    "openai/gpt-5.6-terra": "openai/gpt-6.1-terra",
    "openai/gpt-4.1": "openai/gpt-6.1-terra",
    "openai/gpt-5.6-luna": "openai/gpt-6-luna",
    "openai/gpt-4.1-mini": "openai/gpt-6-luna",
    "whisper-1": "gpt-transcribe",
}


def superseded_replacement(model: str) -> str:
    """Return the current id for a superseded model, or ``model`` unchanged.

    Surrounding whitespace is left intact so identifier validation can reject
    it. Comparison is case-insensitive for a well-formed id.
    """

    if model != model.strip():
        return model
    return SUPERSEDED_MODELS.get(model.lower(), model)


def apply_configured_model(model_id: str) -> str:
    """Rewrite a retired or superseded configured id before a call."""

    if model_id in RETIRED_MODELS:
        replacement = RETIRED_MODELS[model_id]
        logger.warning(
            "Model '%s' is retired (effective %s). "
            "Falling back to '%s'. Update your config to silence this warning.",
            model_id,
            RETIREMENT_DATE,
            replacement,
        )
        model_id = replacement
    replacement = superseded_replacement(model_id)
    if replacement != model_id:
        logger.warning(
            "Model '%s' is superseded. Using '%s'. Update your config to silence this warning.",
            model_id,
            replacement,
        )
        return replacement
    return model_id


def scheduled_model_refusal(model: str, *, today: date | None = None) -> str:
    """Gate published shutdown dates without rewriting historical receipts."""
    normalized = model.strip().lower()
    if normalized == "deep-research-pro-preview-12-2025" and (
        today or datetime.now(UTC).date()
    ) >= date(2026, 10, 23):
        return (
            f"Model '{model}' reached its published earliest shutdown date, 2026-10-23. "
            "Use deep-research-preview-04-2026 for the research workflow, or "
            "gemini-3.8-flash for text analysis. Historical receipts remain readable."
        )
    return ""


def is_xai_media_generation_model(model: str) -> bool:
    """Return true for xAI models that belong to media generation APIs."""
    normalized = model.strip().lower()
    return normalized.startswith(XAI_MEDIA_GENERATION_MODEL_PREFIXES)


def xai_media_generation_refusal(model: str) -> str:
    """Explain why a media model cannot be used through Distill's text route."""
    return (
        f"Model '{model}' is an xAI media generation model, not a Distill text "
        "analysis model. Distill does not call xAI image or video generation APIs; "
        "configure an xAI text model such as grok-4.7 for these workloads."
    )
