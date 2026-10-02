from __future__ import annotations


def _lookup(model: str, pricing: dict[str, dict[str, float]]) -> dict[str, float] | None:
    if model in pricing:
        return pricing[model]
    # dated snapshots, e.g. gpt-5.4-mini-2026-03-17 -> gpt-5.4-mini
    best = None
    for name in pricing:
        if model.startswith(name) and (best is None or len(name) > len(best)):
            best = name
    return pricing[best] if best else None


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int,
                  pricing: dict[str, dict[str, float]]) -> float:
    """Estimated USD cost. Prices are per 1M tokens; cached input is billed at its own rate."""
    price = _lookup(model, pricing)
    if price is None:
        return 0.0
    cached = min(cached_tokens, input_tokens)
    uncached = input_tokens - cached
    cost = (
        uncached * price.get("input", 0.0)
        + cached * price.get("cached_input", price.get("input", 0.0))
        + output_tokens * price.get("output", 0.0)
    ) / 1_000_000
    return round(cost, 6)


def is_priced(model: str, pricing: dict[str, dict[str, float]]) -> bool:
    return _lookup(model, pricing) is not None
