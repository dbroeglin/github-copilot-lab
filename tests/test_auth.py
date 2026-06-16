"""GitHub token resolution, preflight, and secret-redaction name selection.

These never call the network: the ``gh`` fallback is monkeypatched, and the token
value must never be logged or persisted (only its source is surfaced).
"""

from __future__ import annotations

import pytest

from copilot_experiments import auth
from copilot_experiments.auth import (
    AuthError,
    TokenResolution,
    preflight_github_token,
    resolve_github_token,
    secret_env_names,
)
from copilot_experiments.models import Variant


def test_resolve_prefers_env_in_precedence_order():
    env = {"GH_TOKEN": "gh-tok", "GITHUB_TOKEN": "github-tok"}
    res = resolve_github_token(env)
    assert res == TokenResolution(token="gh-tok", source="env:GH_TOKEN")


def test_resolve_copilot_token_wins():
    env = {"COPILOT_GITHUB_TOKEN": "cop", "GH_TOKEN": "gh"}
    assert resolve_github_token(env).source == "env:COPILOT_GITHUB_TOKEN"


def test_resolve_strips_whitespace_and_ignores_blank(monkeypatch):
    monkeypatch.setattr(auth, "_gh_auth_token", lambda: None)
    # A blank value is ignored (falls through to the gh fallback, here None).
    assert resolve_github_token({"GH_TOKEN": "   "}) is None
    # A padded value is stripped.
    res = resolve_github_token({"GH_TOKEN": "  tok  "})
    assert res is not None and res.token == "tok"


def test_resolve_falls_back_to_gh(monkeypatch):
    monkeypatch.setattr(auth, "_gh_auth_token", lambda: "gh-cli-token")
    res = resolve_github_token({})  # no env tokens
    assert res == TokenResolution(token="gh-cli-token", source="gh auth token")


def test_resolve_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(auth, "_gh_auth_token", lambda: None)
    assert resolve_github_token({}) is None


def test_preflight_raises_with_guidance(monkeypatch):
    monkeypatch.setattr(auth, "_gh_auth_token", lambda: None)
    with pytest.raises(AuthError) as exc:
        preflight_github_token({})
    assert "gh auth login" in str(exc.value)


def test_describe_never_leaks_token_characters():
    res = TokenResolution(token="super-secret-value", source="env:GH_TOKEN")
    described = res.describe()
    assert "super-secret-value" not in described
    assert "env:GH_TOKEN" in described


def test_secret_env_names_always_covers_token_vars():
    names = secret_env_names({}, byok_secrets=False)
    assert {"COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"} <= set(names)
    assert "COPILOT_PROVIDER_API_KEY" not in names


def test_secret_env_names_includes_byok_and_custom_secret_keys():
    names = secret_env_names({"MY_API_KEY": "x", "PLAIN": "y"}, byok_secrets=True)
    assert "COPILOT_PROVIDER_API_KEY" in names
    assert "COPILOT_PROVIDER_BEARER_TOKEN" in names
    assert "MY_API_KEY" in names
    assert "PLAIN" not in names


def test_variant_secret_env_round_trip():
    # A token slipped into Variant.env is both redacted on disk and flagged for copilot.
    v = Variant(name="v", env={"SECRET_TOKEN": "abc"})
    assert "SECRET_TOKEN" in secret_env_names(v.env, byok_secrets=False)
    assert "abc" not in str(v.stored())
