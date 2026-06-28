"""Resolve and preflight the GitHub token used to authenticate Copilot CLI.

Leaving authentication to the ``copilot`` subprocess means a missing token is only
discovered *after* Pier has prepared a sandbox and the CLI has spun up -- every
trial then burns time and produces an empty session log. Instead we resolve a token
*once* before the run starts (failing fast if none is available) and inject it into
each trial's environment.

Security -- the token must NEVER be leaked:

* The resolved token is only ever injected into Pier's Copilot CLI agent
  environment at runtime. It is never written to a stored artifact and never
  logged -- only its *source* is reported.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

# Token environment variables Copilot itself recognizes, in resolution precedence order.
GITHUB_TOKEN_ENV_VARS = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")


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
