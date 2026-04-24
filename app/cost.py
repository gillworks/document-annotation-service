from decimal import Decimal

from app.config import Settings


def estimate_cost_usd(
    input_tokens: int | None,
    output_tokens: int | None,
    settings: Settings,
) -> Decimal:
    input_total = Decimal(input_tokens or 0) / Decimal(1_000_000) * settings.input_token_cost_per_1m
    output_total = Decimal(output_tokens or 0) / Decimal(1_000_000) * settings.output_token_cost_per_1m
    return (input_total + output_total).quantize(Decimal("0.000001"))
