import pytest
from offence.pricing import energy_price, sats_per_token


def test_exact_conversion_and_round_up():
    assert sats_per_token('0.0011') == 2
    # 10 cents/kWh * 3600 J/token = .01 cents/token = .1 sat at $100k/BTC.
    result = energy_price('10', '3600', '100000')
    assert result['cents_per_token'] == '0.01'
    assert result['output_msat_per_token'] == 100


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '0', 'garbage'])
def test_invalid_price_inputs(value):
    with pytest.raises(ValueError):
        energy_price(value, '10', '100000')
    with pytest.raises(ValueError):
        sats_per_token(value)


def test_config_applies_pricing_to_offer(config):
    from offence.models import Config
    data = config.model_dump()
    data['pricing'] = {'mode': 'cents-per-kwh', 'cents_per_kwh': '10',
                       'joules_per_token': '3600', 'usd_per_btc': '100000'}
    loaded = Config.model_validate(data)
    assert loaded.offer.output_msat_per_token == 100
