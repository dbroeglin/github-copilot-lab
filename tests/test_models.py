"""Tests for the pydantic models and their helpers."""

from __future__ import annotations

from copilot_experiments import ProviderConfig, Variant


def test_provider_to_env_maps_fields():
    provider = ProviderConfig(
        base_url="http://localhost:11434/v1",
        type="openai",
        api_key="secret-key",
        model_id="llama3.1",
    )
    env = provider.to_env()
    assert env["COPILOT_PROVIDER_BASE_URL"] == "http://localhost:11434/v1"
    assert env["COPILOT_PROVIDER_TYPE"] == "openai"
    assert env["COPILOT_PROVIDER_API_KEY"] == "secret-key"
    assert env["COPILOT_PROVIDER_MODEL_ID"] == "llama3.1"


def test_provider_redacted_masks_secrets():
    provider = ProviderConfig(base_url="http://x", api_key="secret", bearer_token="tok")
    redacted = provider.redacted()
    assert redacted["api_key"] == "***redacted***"
    assert redacted["bearer_token"] == "***redacted***"
    assert redacted["base_url"] == "http://x"


def test_variant_slug():
    assert Variant(name="Opus Medium").slug == "opus-medium"


def test_variant_stored_redacts_provider_secret():
    variant = Variant(
        name="local",
        provider=ProviderConfig(base_url="http://x", api_key="secret"),
    )
    stored = variant.stored()
    assert stored["provider"]["api_key"] == "***redacted***"


def test_variant_stored_redacts_secret_like_env_values():
    # The free-form env escape hatch must not leak a token into variant.json.
    variant = Variant(
        name="byok-via-env",
        env={
            "COPILOT_PROVIDER_API_KEY": "sk-live-123",
            "GITHUB_TOKEN": "ghp_secret",
            "HTTP_AUTHORIZATION": "Bearer abc",
            "MY_PASSWORD": "hunter2",
            "LOG_LEVEL": "debug",  # benign -> preserved
        },
    )
    env = variant.stored()["env"]
    assert env["COPILOT_PROVIDER_API_KEY"] == "***redacted***"
    assert env["GITHUB_TOKEN"] == "***redacted***"
    assert env["HTTP_AUTHORIZATION"] == "***redacted***"
    assert env["MY_PASSWORD"] == "***redacted***"
    assert env["LOG_LEVEL"] == "debug"
