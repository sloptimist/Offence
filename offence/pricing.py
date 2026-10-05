"""Exact pricing conversion. Measurements and exchange rates are explicit operator inputs."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING


def positive(value, name):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'Invalid {name}') from exc
    if not result.is_finite() or result <= 0 or result > Decimal('1e15'):
        raise ValueError(f'Invalid {name}')
    return result


def sats_per_token(value):
    msat = int((positive(value, 'sats per token') * 1000).to_integral_value(rounding=ROUND_CEILING))
    if msat > 1_000_000_000:
        raise ValueError('Token price exceeds protocol limit')
    return msat


def energy_price(cents_per_kwh, joules_per_token, usd_per_btc):
    # One kWh is 3,600,000 joules. This is the electricity component only.
    cents = positive(cents_per_kwh, 'cents per kWh') * positive(joules_per_token, 'joules per token') / 3_600_000
    sats = cents / 100 / positive(usd_per_btc, 'USD per BTC') * 100_000_000
    return {'cents_per_token': str(cents), 'output_msat_per_token': sats_per_token(sats)}
