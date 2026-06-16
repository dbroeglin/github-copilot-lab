"""Resolve and preflight the GitHub token used to authenticate Copilot CLI.

Leaving authentication to the ``copilot`` subprocess means a missing token is only
discovered *after* a workspace has been provisioned and the CLI has spun up -- every
trial then burns time and produces an empty session log. Instead we resolve a token
*once* before the run starts (failing fast if none is available) and inject it into
each trial's environment.

Security -- the token must NEVER be leaked:

* The resolved token is only ever placed in a child process's environment at runtime
  (via :attr:`~copilot_experiments.invoker.Invocation.env_overrides`). It is never
  written to a stored artifact and never logged -- only its *source* is reported.
* The names of the variables that carry it (plus any BYOK provider secrets) are passed
  to ``copilot --secret-env-vars`` so the CLI strips them from shell/MCP environments
  and redacts their values from its own output: stdout, and the ``--share`` markdown
  transcript.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

# Token environment variables Copilot itself recognizes, in resolution precedence order.
GITHUB_TOKEN_ENV_VARS = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")

# The variable the resolved token is injected under for the Copilot child process.
INJECTED_TOKEN_ENV_VAR = "COPILOT_GITHUB_TOKEN"

# Provider (BYOK) environment variables whose values are secrets and must be redacted.
_PROVIDER_SECRET_ENV_VARS = ("COPILOT_PROVIDER_API_KEY", "COPILOT_PROVIDER_BEARER_TOKEN")


class AuthError(RuntimeError):
    """No usable GitHub token could be resolved for the run."""


@dataclass(frozen=True)
class TokenResolution:
    """A resolved token plus where it came from.

    ``source`` is safe to print (e.g. ``"env:GH_TOKEN"`` or ``"gh auth token"``); the
    ``token`` itself must never be logged or persisted.
    """

    token: str
    source: str

    def describe(self) -> str:
        """A leak-free, human-readable description (source + length, no token chars)."""
        return f"{self.source} ({len(self.token)} chars)"


def resolve_github_token(env: Mapping[str, str] | None = None) -> TokenResolution | None:
    """Resolve a GitHub token for Copilot, or ``None`` if none is available.

    Checks the recognized environment variables in precedence order, then falls back
    to ``gh auth token``. The token value is never logged.
    """
    environ = os.environ if env is None else env
    for name in GITHUB_TOKEN_ENV_VARS:
        value = environ.get(name)
        if value and value.strip():
            return TokenResolution(token=value.strip(), source=f"env:{name}")

    token = _gh_auth_token()
    if token:
        return TokenResolution(token=token, source="gh auth token")
    return None


def _gh_auth_token() -> str | None:
    """Return the token from ``gh auth token``, or ``None`` if unavailable."""
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        proc = subprocess.run(
            [gh, "auth", "token"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    token = proc.stdout.strip()
    return token or None


def preflight_github_token(env: Mapping[str, str] | None = None) -> TokenResolution:
    """Resolve a token or raise :class:`AuthError` with actionable guidance.

    Called once before a run starts so a missing token aborts immediately instead of
    failing every trial after provisioning.
    """
    resolution = resolve_github_token(env)
    if resolution is None:
        raise AuthError(
            "No GitHub authentication found for Copilot. Set one of "
            f"{', '.join(GITHUB_TOKEN_ENV_VARS)}, or run 'gh auth login'."
        )
    return resolution


def secret_env_names(variant_env: Mapping[str, str], *, byok_secrets: bool) -> list[str]:
    """Names whose values Copilot must redact from output and strip from sub-shells.

    Always includes the GitHub token variables (so an injected or inherited token is
    never echoed). Adds BYOK provider secret variables when the variant uses a provider
    with secrets, plus any free-form ``variant.env`` keys that look like a secret.
    """
    from .models import _SECRET_ENV_HINT

    names: set[str] = set(GITHUB_TOKEN_ENV_VARS)
    if byok_secrets:
        names.update(_PROVIDER_SECRET_ENV_VARS)
    for key in variant_env:
        if _SECRET_ENV_HINT.search(key):
            names.add(key)
    return sorted(names)
