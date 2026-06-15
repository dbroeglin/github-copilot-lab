"""AIU (AI Unit) cost math for Copilot token usage.

GitHub bills Copilot model usage in **AIU**. The Copilot CLI session log reports cost as
``totalNanoAiu`` (1 AIU == 1e9 nano-AIU) and, crucially, embeds the *price* of each token type in
``session.compaction_complete`` events as ``costPerBatch`` (nano-AIU per ``batchSize`` tokens).

The session total AIU is authoritative; what this module adds is the ability to **decompose** that
total across the four token types (so we can say *where the money goes*), using live rates when the
log exposes them and documented defaults otherwise.

Premium requests are intentionally ignored: GitHub stopped using them on 2026-06-01.
"""

from __future__ import annotations

from typing import Any

NANO_PER_AIU = 1_000_000_000

#: Token types Copilot meters, cheapest-to-priciest per token.
TOKEN_TYPES: tuple[str, ...] = ("input", "cache_read", "cache_write", "output")

#: Default price per token type, in nano-AIU per 1e6 tokens, as observed in real
#: ``session.compaction_complete`` payloads (cache_read is ~10x cheaper than fresh input;
#: output is ~5x input). Used only when a log does not carry live ``costPerBatch`` rates.
_DEFAULT_BATCH_SIZE = 1_000_000
DEFAULT_COST_PER_BATCH: dict[str, int] = {
    "input": 300_000_000_000,
    "cache_read": 30_000_000_000,
    "cache_write": 375_000_000_000,
    "output": 1_500_000_000_000,
}


def default_rates() -> dict[str, float]:
    """Documented fallback price per *single* token, in nano-AIU, keyed by token type."""
    return {k: v / _DEFAULT_BATCH_SIZE for k, v in DEFAULT_COST_PER_BATCH.items()}


def rates_from_compaction(data: dict[str, Any]) -> dict[str, float] | None:
    """Extract live per-token nano-AIU rates from a ``session.compaction_complete`` payload.

    Looks for ``compactionTokensUsed.copilotUsage.tokenDetails`` -- a list of
    ``{tokenType, costPerBatch, batchSize}`` entries. Returns ``None`` when absent or malformed.
    """
    details = (
        (data.get("compactionTokensUsed") or {})
        .get("copilotUsage", {})
        .get("tokenDetails")
    )
    if not isinstance(details, list):
        return None
    rates: dict[str, float] = {}
    for entry in details:
        if not isinstance(entry, dict):
            continue
        ttype = entry.get("tokenType")
        cost = entry.get("costPerBatch")
        batch = entry.get("batchSize")
        if isinstance(ttype, str) and isinstance(cost, (int, float)) and batch:
            rates[ttype] = float(cost) / float(batch)
    return rates or None


def aiu_by_type(
    counts: dict[str, int | None],
    rates: dict[str, float] | None = None,
    *,
    normalize_to_nano: float | int | None = None,
) -> dict[str, float]:
    """Decompose a per-type token count map into AIU per token type.

    ``rates`` are per-token nano-AIU prices (defaults to :func:`default_rates`). When
    ``normalize_to_nano`` (an authoritative ``totalNanoAiu``) is given and the priced total is
    positive, the split is scaled so it sums exactly to that total -- absorbing any rate drift
    across models/tiers while keeping the *authoritative* grand total intact.
    """
    rates = rates or default_rates()
    nano: dict[str, float] = {}
    for ttype in TOKEN_TYPES:
        count = counts.get(ttype) or 0
        nano[ttype] = float(count) * rates.get(ttype, 0.0)
    priced_total = sum(nano.values())
    if normalize_to_nano is not None and priced_total > 0:
        scale = float(normalize_to_nano) / priced_total
        nano = {k: v * scale for k, v in nano.items()}
    return {k: round(v / NANO_PER_AIU, 6) for k, v in nano.items()}


def to_aiu(nano_aiu: float | int | None) -> float | None:
    """Convert nano-AIU to AIU, or ``None`` through."""
    if nano_aiu is None:
        return None
    return round(float(nano_aiu) / NANO_PER_AIU, 6)
