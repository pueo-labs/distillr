# pyright: strict
"""Tests for the provider catalog used by CLI routing UX."""

from __future__ import annotations

import pytest

from distill.llm.provider_catalog import (
    default_model_for_provider,
    infer_cloud_provider_for_model,
    known_models_for_provider,
    normalize_provider_name,
    price_summary,
    pricing_audit_for_provider,
    validate_provider_route,
)


def test_normalize_provider_aliases() -> None:
    assert normalize_provider_name("Google") == "gemini"
    assert normalize_provider_name("grok") == "xai"
    assert normalize_provider_name("claude") == "anthropic"


def test_normalize_provider_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        normalize_provider_name("azure")


def test_default_models() -> None:
    assert default_model_for_provider("xai") == "grok-4.7"
    assert default_model_for_provider("gemini") == "gemini-3.8-flash"
    assert default_model_for_provider("anthropic") == "claude-sonnet-5-5"
    assert default_model_for_provider("ollama") == ""
    assert default_model_for_provider("openrouter") == "deepseek/deepseek-v4.1-flash"


def test_openrouter_catalog_includes_deepseek_models() -> None:
    models = known_models_for_provider("openrouter")
    assert models[0] == "deepseek/deepseek-v4.1-flash"
    assert "deepseek/deepseek-v4-flash" in models
    assert "deepseek/deepseek-v4-pro" in models
    assert "deepseek/deepseek-v4-pro-0813" in models
    assert "deepseek/deepseek-v3.2" in models
    assert "deepseek/deepseek-chat" in models
    assert "deepseek/deepseek-r1" in models
    assert "z-ai/glm-5.3-flash" in models
    assert "z-ai/glm-5.3" in models
    assert "qwen/qwen3.8-flash" in models
    assert "qwen/qwen3.8-max-0902" in models
    assert {
        "z-ai/glm-5.3-flashx",
        "z-ai/glm-5.3-prime",
        "qwen/qwen3.8-max-prime",
        "qwen/qwen3.8-omni-flash",
        "x-ai/grok-4.7",
        "google/gemini-3.8-flash",
        "anthropic/claude-opus-5.5",
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-fable-5.2",
        "openai/gpt-6.1-sol",
        "openai/gpt-6.1-terra",
        "google/gemini-4-carbon",
    }.issubset(models)


def test_gemini_catalog_includes_new_flash_models() -> None:
    models = known_models_for_provider("gemini")
    assert models == ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-4-carbon"]


def test_current_xai_and_anthropic_models_are_catalogued() -> None:
    xai_models = known_models_for_provider("xai")
    anthropic_models = known_models_for_provider("anthropic")

    assert xai_models == ["grok-4.7"]
    assert anthropic_models[0] == "claude-sonnet-5-5"
    assert "claude-fable-5-2" in anthropic_models
    assert "claude-fable-5.2" not in anthropic_models
    assert "claude-opus-5.5" not in anthropic_models
    assert "claude-sonnet-5.5" not in anthropic_models
    assert "claude-opus-5-5" in anthropic_models
    assert "claude-sonnet-5-5" in anthropic_models
    assert "claude-haiku-5-5" in anthropic_models
    assert "claude-sonnet-5" not in anthropic_models


def test_infer_cloud_provider_for_model() -> None:
    assert infer_cloud_provider_for_model("gemini-3.8-flash") == "gemini"
    assert infer_cloud_provider_for_model("gemini-4-carbon") == "gemini"
    assert infer_cloud_provider_for_model("grok-4.7") == "xai"
    assert infer_cloud_provider_for_model("claude-sonnet-5-5") == "anthropic"
    assert infer_cloud_provider_for_model("deepseek/deepseek-v4.1-flash") == "openrouter"
    assert infer_cloud_provider_for_model("z-ai/glm-5.3-flash") == "openrouter"
    assert infer_cloud_provider_for_model("qwen/qwen3.8-flash") == "openrouter"
    assert infer_cloud_provider_for_model("qwen3.5:27b") == ""


def test_validate_provider_route_rejects_cross_family() -> None:
    with pytest.raises(ValueError, match="belongs to provider"):
        validate_provider_route("xai", "gemini-3.8-flash")


def test_validate_provider_route_accepts_matching_pair() -> None:
    assert validate_provider_route("gemini", "gemini-3.5-flash-lite") == (
        "gemini",
        "gemini-3.5-flash-lite",
    )


def test_validate_openrouter_requires_concrete_model_slug() -> None:
    assert validate_provider_route("openrouter", "x-ai/grok-4.7") == (
        "openrouter",
        "x-ai/grok-4.7",
    )
    with pytest.raises(ValueError, match="router models"):
        validate_provider_route("openrouter", "openrouter/auto")
    with pytest.raises(ValueError, match="lowercase concrete"):
        validate_provider_route("openrouter", "anthropic/claude-sonnet-5.5-5:free")


def test_price_summary_for_catalog_models() -> None:
    from distill.llm.cost import get_pricing

    rates = get_pricing("gemini-3.8-flash")
    summary = price_summary("gemini-3.8-flash")
    assert f"{rates['input']:.2f}" in summary
    assert f"{rates['output']:.2f}" in summary
    assert "0.30" in price_summary("gemini-3.5-flash-lite")
    assert "200,000+" in price_summary("grok-4.7")
    assert "$4.00/$12.00" in price_summary("grok-4.7")


@pytest.mark.parametrize("provider", ["xai", "gemini", "anthropic", "openrouter"])
def test_routable_cloud_catalogs_have_auditable_pricing_sources(provider: str) -> None:
    audit = pricing_audit_for_provider(provider)
    assert audit["verified_on"] == ("2026-10-17" if provider == "gemini" else "2026-10-06")
    assert audit["source"].startswith("https://")


def test_local_and_host_routes_do_not_claim_vendor_pricing_sources() -> None:
    assert pricing_audit_for_provider("ollama") == {}
    assert pricing_audit_for_provider("lmstudio") == {}
    assert pricing_audit_for_provider("agent") == {}
