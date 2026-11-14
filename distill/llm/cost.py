# pyright: strict
"""Cost registry — pricing data and cost computation for LLM models.

Centralises per-model pricing so that ``distill/costs.py`` (run-level
aggregation) and the telemetry module can both compute costs from a single
source of truth.  Supports per-token and per-query pricing models.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)

GEMINI_DEEP_RESEARCH_MODEL: str = "gemini-deep-research"
GEMINI_DEEP_RESEARCH_COST: float = 2.50
# Google bills Deep Research for underlying model tokens and tools rather than
# at a flat query price. Distill retains non-binding planning placeholders for
# estimates and display. They are never treated as an actual or enforceable cap.
DEEP_RESEARCH_MAX_COST: float = 5.00
DEEP_RESEARCH_MODEL_ALIASES: tuple[str, ...] = (
    GEMINI_DEEP_RESEARCH_MODEL,
    "deep-research",
    "deep-research-preview-04-2026",
    "deep-research-max-preview-04-2026",
    "deep-research-pro-preview-12-2025",  # superseded 2026-04; kept for historical cost
)
_GEMINI_DEEP_RESEARCH_PRICING: dict[str, float] = {"per_query": GEMINI_DEEP_RESEARCH_COST}
_DEEP_RESEARCH_MAX_PRICING: dict[str, float] = {"per_query": DEEP_RESEARCH_MAX_COST}
_GEMINI_FLASH_INTRO_PRICING_END = date(2026, 12, 31)
_GEMINI_FLASH_INTRO_PRICING: dict[str, float] = {"input": 0.75, "output": 3.75}
_GEMINI_FLASH_STANDARD_PRICING: dict[str, float] = {"input": 1.50, "output": 7.50}
_GEMINI_CARBON_INTRO_END = date(2026, 11, 30)
_GEMINI_CARBON_INTRO: dict[str, float] = {"input": 2.00, "output": 10.00}
_GEMINI_CARBON_STANDARD: dict[str, float] = {"input": 4.00, "output": 20.00}

# Registry review metadata is deliberately code-visible so operators and tests
# can distinguish a recently verified price from an old hard-coded guess. CI
# never scrapes vendor pages or contacts a paid API.
# The dated audit scopes current routes; retained legacy rates are historical.
PRICING_VERIFIED_ON: str = "2026-10-06"
PROVIDER_PRICING_VERIFIED_ON: dict[str, str] = {"gemini": "2026-10-17"}
PRICING_SOURCE_URLS: dict[str, str] = {
    "xai": "https://docs.x.ai/developers/models",
    "gemini": "https://ai.google.dev/gemini-api/docs/pricing",
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "openai": "https://developers.openai.com/api/docs/models/compare",
    "openrouter": "https://openrouter.ai/models",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing",
}

# Cloud speech-to-text pricing, USD per hour of audio (batch rates). Local
# faster-whisper is free. Keyed by the provider/model string TranscriptionResult
# reports, so both are accepted.
# ``gpt-transcribe`` is $0.0045 per minute ($0.27 per hour), verified
# 2026-11-14 at https://developers.openai.com/api/docs/models/gpt-transcribe.
# The bare ``openai`` provider key uses that current file-transcription rate.
# A recorded model id wins over the provider key.
TRANSCRIPTION_PRICING: dict[str, float] = {
    "xai-grok-stt": 0.10,
    "grok-stt": 0.10,
    "openai": 0.27,
    "gpt-transcribe": 0.27,
    "local": 0.0,
    "faster-whisper": 0.0,
}
MAX_TRANSCRIPTION_DURATION_SECONDS = 10 * 365 * 24 * 60 * 60

# ---------------------------------------------------------------------------
# Pricing per 1 M tokens.  Per-query models use a ``per_query`` key instead.
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    # Gemini 4 Carbon uses introductory rates through 2026-11-30. get_pricing()
    # resolves that window. The stored row is the post-intro rate.
    "gemini-4-carbon": _GEMINI_CARBON_STANDARD,
    # xAI bills the higher rates for every token in a request once its prompt
    # reaches 200K tokens. Cached-input discounts are intentionally omitted:
    # Distill does not yet receive a provider-accurate cached-token count, so
    # authorization stays conservative at the uncached rate.
    "grok-4.7": {
        "input": 2.00,
        "output": 6.00,
        "long_context_min_input": 200_000,
        "long_input": 4.00,
        "long_output": 12.00,
    },
    # Gemini 3.8 Flash uses launch pricing through 2026-12-31. get_pricing()
    # resolves the date window so estimates change on 2027-01-01.
    "gemini-3.8-flash": _GEMINI_FLASH_INTRO_PRICING,
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    # Planning estimates for one Deep Research run. Actual Google billing is
    # based on underlying model inference and tool usage.
    GEMINI_DEEP_RESEARCH_MODEL: _GEMINI_DEEP_RESEARCH_PRICING,
    "deep-research": _GEMINI_DEEP_RESEARCH_PRICING,
    "deep-research-preview-04-2026": _GEMINI_DEEP_RESEARCH_PRICING,
    # Broad "deep-research-max" alias so any dated Max variant prices at the Max
    # rate via prefix match (with longest-prefix-wins in get_pricing), not the
    # cheaper standard "deep-research" alias.
    "deep-research-max": _DEEP_RESEARCH_MAX_PRICING,
    "deep-research-max-preview-04-2026": _DEEP_RESEARCH_MAX_PRICING,
    "deep-research-pro-preview-12-2025": _GEMINI_DEEP_RESEARCH_PRICING,
    # Anthropic API pricing. Mythos 5.2 is the limited-availability twin of
    # Fable 5.2. Haiku 5.5 charges the long rates for the whole request once
    # the prompt exceeds 100K tokens.
    "claude-fable-5-2": {"input": 8.00, "output": 40.00},
    "claude-fable-5.2": {"input": 8.00, "output": 40.00},
    "claude-mythos-5-2": {"input": 8.00, "output": 40.00},
    "claude-mythos-5.2": {"input": 8.00, "output": 40.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "claude-opus-5.5": {"input": 4.00, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
    "claude-sonnet-5.5": {"input": 2.00, "output": 10.00},
    "claude-haiku-5-5": {
        "input": 0.10,
        "output": 0.50,
        "long_context_min_input": 100_001,
        "long_input": 0.50,
        "long_output": 2.50,
    },
    "claude-haiku-5.5": {
        "input": 0.10,
        "output": 0.50,
        "long_context_min_input": 100_001,
        "long_input": 0.50,
        "long_output": 2.50,
    },
    # OpenAI reserved route pricing. The route remains unimplemented, but
    # registry entries keep future estimates and historical ledgers honest.
    "gpt-6-astra": {
        "input": 10.00,
        "output": 50.00,
        "long_context_min_input": 272_001,
        "long_input": 20.00,
        "long_output": 75.00,
    },
    "gpt-6.1-sol": {
        "input": 2.00,
        "output": 10.00,
        "long_context_min_input": 272_001,
        "long_input": 4.00,
        "long_output": 15.00,
    },
    "gpt-6.1-terra": {
        "input": 1.00,
        "output": 5.00,
        "long_context_min_input": 272_001,
        "long_input": 2.00,
        "long_output": 7.50,
    },
    "gpt-6-luna": {
        "input": 0.10,
        "output": 0.50,
        "long_context_min_input": 272_001,
        "long_input": 0.20,
        "long_output": 0.75,
    },
    # DeepSeek models (available via OpenRouter and local runtimes)
    "deepseek/deepseek-v4.1-flash": {"input": 0.30, "output": 1.20},
    # Scheduled OpenRouter promotions can halve these rates. Authorize at the
    # full rate so a call crossing a UTC pricing window remains bounded.
    "deepseek/deepseek-v4-pro-0813": {"input": 1.32, "output": 3.96},
    "deepseek/deepseek-v4-pro": {"input": 0.2088, "output": 0.4176},
    "deepseek/deepseek-v4-flash": {"input": 0.03, "output": 1.28},
    "deepseek/deepseek-v3.2": {"input": 0.28, "output": 0.42},
    "deepseek/deepseek-chat": {"input": 0.2574, "output": 1.0287},
    "deepseek/deepseek-r1": {"input": 0.70, "output": 2.50},
    "deepseek-v4.1-flash": {"input": 0.30, "output": 1.20},
    "deepseek-v4-flash": {"input": 0.09, "output": 0.18},
    "deepseek-v4-pro": {"input": 1.60, "output": 3.20},
    "deepseek-v3.2": {"input": 0.27, "output": 0.40},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-r1": {"input": 0.55, "output": 2.19},
    # Zhipu AI GLM models (available via OpenRouter)
    # Exact OpenRouter rates take precedence over supplier estimates below.
    "z-ai/glm-5.3-flash": {"input": 0.15, "output": 0.50},
    "z-ai/glm-5.3": {"input": 0.07, "output": 7.00},
    "z-ai/glm-5.3-flashx": {"input": 0.37, "output": 1.25},
    "z-ai/glm-5.3-prime": {"input": 2.80, "output": 8.80},
    "glm-5.3-flash": {"input": 0.09, "output": 0.30},
    "glm-5.3": {"input": 1.40, "output": 4.40},
    # Alibaba Qwen models (available via OpenRouter)
    "qwen3.8-flash": {"input": 0.15, "output": 0.47},
    "qwen3.8-max-0902": {"input": 2.00, "output": 6.00},
    "qwen3.8-max": {"input": 2.00, "output": 6.00},
    "qwen/qwen3.8-max-prime": {"input": 4.00, "output": 12.00},
    "qwen/qwen3.8-omni-flash": {"input": 0.15, "output": 0.47},
}

DEFAULT_MODEL: str = "grok-4.7"


def deep_research_query_cost(model: str = "") -> float:
    """Return the pre-run planning estimate for a Gemini Deep Research job.

    Model-aware: ``deep-research-max-preview-04-2026`` is ~$5/query, the standard
    variants ~$2.50. Actual billing is token and tool based. An empty model
    falls back to the standard estimate.
    """
    name = model or GEMINI_DEEP_RESEARCH_MODEL
    return get_pricing(name).get("per_query", GEMINI_DEEP_RESEARCH_COST)


def normalize_transcription_duration(seconds: object) -> float:
    """Return a finite, nonnegative duration within the accounting bound."""

    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ValueError("transcription duration must be a real number")
    try:
        normalized = float(seconds)
    except (OverflowError, ValueError) as exc:
        raise ValueError("transcription duration is outside the supported range") from exc
    if (
        not math.isfinite(normalized)
        or normalized < 0
        or normalized > MAX_TRANSCRIPTION_DURATION_SECONDS
    ):
        raise ValueError(
            "transcription duration must be finite and between 0 and "
            f"{MAX_TRANSCRIPTION_DURATION_SECONDS} seconds"
        )
    return normalized


def _transcription_rate(provider: str, model: str = "") -> float | None:
    """Prefer a known model rate, then the provider rate."""

    model_key = model.strip().lower()
    if model_key in TRANSCRIPTION_PRICING:
        return TRANSCRIPTION_PRICING[model_key]
    return TRANSCRIPTION_PRICING.get(provider)


def transcription_cost(provider: str, seconds: object, *, model: str = "") -> float:
    """USD for ``seconds`` of audio at the per-hour speech-to-text rate.

    Returns 0 for local or unknown providers. ``provider`` is the provider or
    model string from ``TranscriptionResult`` (for example ``"xai-grok-stt"``
    or ``"gpt-transcribe"``). When ``model`` has its own rate, that rate is used.
    """
    duration = normalize_transcription_duration(seconds)
    rate = _transcription_rate(provider, model)
    if rate is None:
        return 0.0
    return rate * duration / 3600.0


def has_known_transcription_pricing(provider: str, *, model: str = "") -> bool:
    """Return whether *provider* or *model* has an explicit duration-based rate."""

    return _transcription_rate(provider, model) is not None


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute estimated cost in USD for an LLM call.

    For per-token models the formula is::

        (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    Models with a registered long-context threshold use their long-context
    rates for every token once ``input_tokens`` reaches that threshold. For
    planning-only per-query entries (e.g. ``gemini-deep-research``) the
    non-binding placeholder is returned directly, ignoring token counts.
    """
    rates = get_pricing(model)
    if "per_query" in rates:
        return rates["per_query"]
    input_rate = rates.get("input", 0.0)
    output_rate = rates.get("output", 0.0)
    long_context_min_input = rates.get("long_context_min_input")
    if long_context_min_input is not None and input_tokens >= long_context_min_input:
        input_rate = rates.get("long_input", input_rate)
        output_rate = rates.get("long_output", output_rate)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def get_pricing(model: str) -> dict[str, float]:
    """Look up pricing for *model*, with prefix-match and default fallback.

    Resolution order:
    1. Exact provider-specific route in ``PRICING``.
    2. Date-resolved temporary pricing windows.
    3. Exact underlying model or longest-prefix compatibility match.
    4. Fall back to ``DEFAULT_MODEL`` and log a warning.
    """
    # Normalize first: catalog keys are lowercase, but a model id reaches here
    # in whatever case the operator configured. Routing case-folds, so
    # "Claude-Opus-5-5" resolves to a provider and, without this fold, missed
    # every pricing key and silently fell back to DEFAULT_MODEL. Under-reporting
    # spend is the dangerous direction for the ledger, budget caps, and
    # projections, so match case-insensitively.
    resolved = _resolve_known_pricing(model)
    if resolved is not None:
        return resolved
    logger.warning(
        "No pricing found for model '%s'; falling back to '%s'",
        model,
        DEFAULT_MODEL,
    )
    return PRICING[DEFAULT_MODEL]


def has_known_pricing(model: str) -> bool:
    """Return whether *model* resolves to an explicit registry price."""

    return _resolve_known_pricing(model) is not None


def is_nonbinding_planning_price(model: str) -> bool:
    """Return whether *model* is a planning placeholder, not a token price.

    Gemini Deep Research aliases stay in the registry for estimates and
    display. They must not authorize or ledger a hard dollar amount.
    """

    rates = _resolve_known_pricing(model)
    return rates is not None and "per_query" in rates


def _resolve_known_pricing(model: str) -> dict[str, float] | None:
    from distill.llm.openrouter_policy import underlying_model_id

    route_id = model.strip().lower()
    # A routed endpoint can charge differently from the original supplier.
    # Keep exact provider identity before resolving compatibility aliases.
    if (
        route_id in PRICING
        and not _is_intro_priced_gemini_flash_model(route_id)
        and not route_id.startswith("gemini-4-carbon")
    ):
        return PRICING[route_id]
    if "/" in route_id:
        routed = _prefix_pricing(route_id, routed_only=True)
        if routed is not None:
            return routed
    normalized = underlying_model_id(model)
    if not normalized:
        return None
    if normalized.startswith("gemini-4-carbon"):
        return _gemini_carbon_pricing()
    if _is_intro_priced_gemini_flash_model(normalized):
        return _gemini_flash_pricing()
    if normalized in PRICING:
        return PRICING[normalized]
    # Prefix matching for versioned model names. Longest key first so the most
    # specific prefix wins -- otherwise a broad alias like "deep-research" would
    # shadow "deep-research-max-..." ($5) and silently price it at the standard
    # $2.50 rate.
    return _prefix_pricing(normalized)


def _prefix_pricing(model: str, *, routed_only: bool = False) -> dict[str, float] | None:
    for key in sorted(PRICING, key=len, reverse=True):
        if (not routed_only or "/" in key) and model.startswith(key):
            return PRICING[key]
    return None


def pricing_source_for_model(model: str) -> str:
    """Return the authoritative pricing page for a cloud model, if known."""

    normalized = model.strip().lower()
    if "/" in normalized:
        return PRICING_SOURCE_URLS["openrouter"]
    if normalized.startswith("grok-"):
        return PRICING_SOURCE_URLS["xai"]
    if normalized.startswith(("gemini-", "deep-research")):
        return PRICING_SOURCE_URLS["gemini"]
    if normalized.startswith("claude-"):
        return PRICING_SOURCE_URLS["anthropic"]
    if normalized.startswith("gpt-"):
        return PRICING_SOURCE_URLS["openai"]
    if normalized.startswith("deepseek-"):
        return PRICING_SOURCE_URLS["deepseek"]
    return ""


def _is_intro_priced_gemini_flash_model(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("gemini-3.8-flash")


def _gemini_flash_pricing() -> dict[str, float]:
    if _pricing_reference_date() <= _GEMINI_FLASH_INTRO_PRICING_END:
        return _GEMINI_FLASH_INTRO_PRICING
    return _GEMINI_FLASH_STANDARD_PRICING


def _gemini_carbon_pricing() -> dict[str, float]:
    if _pricing_reference_date() <= _GEMINI_CARBON_INTRO_END:
        return _GEMINI_CARBON_INTRO
    return _GEMINI_CARBON_STANDARD


def _pricing_reference_date() -> date:
    return datetime.now(UTC).date()
