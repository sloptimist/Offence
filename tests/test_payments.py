import asyncio
import hashlib
import time

import pytest

from offence.app import create_app
from offence.crypto import Identity, b64, digest, unseal
from offence.lightning import LndRegtest
from conftest import request


class WalletSimulator:
    """Test-only ledger. Never reachable through a production configuration."""
    def __init__(self):
        self.invoices = {}

    async def check_network(self):
        pass

    async def invoice(self, preimage, amount, commitment, expiry):
        payment_hash = hashlib.sha256(preimage).hexdigest()
        self.invoices[payment_hash] = (preimage, amount, commitment, asyncio.Event())
        return "simulator:" + payment_hash

    async def wait(self, payment_hash, amount, timeout):
        await self.invoices[payment_hash][3].wait()
        return True

    def pay(self, payment_hash):
        preimage, _, _, event = self.invoices[payment_hash]
        event.set()
        return preimage


async def test_provider_withholds_next_batch_until_payment_and_key_recovers_first(config, manifest, tmp_path):
    config.offer.output_msat_per_token = 50
    wallet = WalletSimulator()
    app = create_app(tmp_path, config, wallet=wallet, background=False)
    p, buyer = app.state.provider, Identity()
    quote = p.quote(request(buyer, p.identity.public, manifest, max_total_msat=400))
    accepted = buyer.sign({"type": "accept", "session": quote["body"]["session"], "quote_hash": digest(quote)})
    stream = p.stream(*p.accept(accepted))
    first = await anext(stream)
    assert first["body"]["free_key"] is None
    assert first["body"]["sealed"]["header"]["amount_msat"] == 100
    next_batch = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    assert not next_batch.done()
    preimage = wallet.pay(first["body"]["sealed"]["payment_hash"])
    assert unseal(first["body"]["sealed"], preimage)["groups"][0]["text"] == "This "
    await next_batch
    assert p.store.evidence()["settled_batches"] == 1
    await stream.aclose()
    assert p.active == 0
    recovered = p.store.recover(quote["body"]["session"], buyer.public)
    assert recovered["batches"][0] == first


async def test_failed_payment_stops_generation_without_charging_future_tokens(config, manifest, tmp_path):
    class Unpaid(WalletSimulator):
        async def wait(self, *args):
            return False
    config.offer.output_msat_per_token = 5
    app = create_app(tmp_path, config, wallet=Unpaid(), background=False)
    p, buyer = app.state.provider, Identity()
    q = p.quote(request(buyer, p.identity.public, manifest, max_total_msat=40))
    accepted = buyer.sign({"type": "accept", "session": q["body"]["session"], "quote_hash": digest(q)})
    messages = [x async for x in p.stream(*p.accept(accepted))]
    assert [m["body"]["type"] for m in messages] == ["batch", "error"]
    assert p.store.evidence()["settled_batches"] == 0
    assert p.active == 0


@pytest.mark.parametrize("network", ["mainnet", "testnet", "signet", "", None])
async def test_lnd_network_guard(network):
    wallet = object.__new__(LndRegtest)
    async def call(*args):
        return {"chains": [{"chain": "bitcoin", "network": network}]}
    wallet.call = call
    with pytest.raises(ValueError, match="regtest"):
        await wallet.check_network()


async def test_lnd_invoice_and_payment_contract_validation():
    wallet = object.__new__(LndRegtest)
    preimage, commitment = b"a" * 32, "c" * 64
    payment_hash = hashlib.sha256(preimage).hexdigest()
    calls = []
    async def call(method, path, data=None):
        calls.append((method, path, data))
        if path == "/v1/getinfo":
            return {"chains": [{"chain": "bitcoin", "network": "regtest"}]}
        if path == "/v1/invoices":
            assert data["r_preimage"] == b64(preimage)
            assert data["value_msat"] == "100"
            assert data["description_hash"] == b64(bytes.fromhex(commitment))
            return {"r_hash": b64(bytes.fromhex(payment_hash)), "payment_request": "lnbcrt-test"}
        if path.startswith("/v1/payreq/"):
            return {"payment_hash": payment_hash, "num_msat": "100", "description_hash": commitment,
                    "timestamp": str(int(time.time())), "expiry": "60"}
        if path == "/v1/channels/transactions":
            assert data["fee_limit"] == {"fixed_msat": "10"}
            return {"payment_preimage": b64(preimage), "payment_error": ""}
        raise AssertionError(path)
    wallet.call = call
    invoice = await wallet.invoice(preimage, 100, commitment, 60)
    assert await wallet.pay(invoice, payment_hash, 100, commitment, 10) == preimage
    with pytest.raises(ValueError):
        await wallet.pay(invoice, payment_hash, 101, commitment, 10)
    assert len([c for c in calls if c[1] == "/v1/channels/transactions"]) == 1


async def test_lnd_never_accepts_mainnet_invoice():
    wallet = object.__new__(LndRegtest)
    async def call(*args):
        return {"chains": [{"chain": "bitcoin", "network": "regtest"}]}
    wallet.call = call
    with pytest.raises(ValueError, match="regtest"):
        await wallet.pay("lnbc1malicious", "0" * 64, 1, "0" * 64, 0)


@pytest.mark.parametrize('change', [
    {'payment_hash': '0' * 64}, {'value_msat': '101'},
    {'payment_preimage': '00' * 32}, {'fee_msat': '11'}, {'fee_msat': '-1'},
])
def test_tracking_rejects_wrong_contract(change):
    preimage = b'a' * 32
    payment_hash = hashlib.sha256(preimage).hexdigest()
    result = dict(payment_hash=payment_hash, value_msat='100', payment_preimage=preimage.hex(),
                  fee_msat='10', status='SUCCEEDED')
    result.update(change)
    with pytest.raises(ValueError):
        LndRegtest.validate_tracking(result, payment_hash, 100, 10)


async def test_restart_recovers_key_without_resending_payment(tmp_path):
    from offence.client import Buyer
    from offence.crypto import seal
    provider, identity = Identity(), Identity()
    preimage = b'a' * 32
    sealed = seal({'groups': [{'text': 'ok', 'token_ids': [1]}]},
                  {'amount_msat': 100}, preimage)
    batch = provider.sign({'type': 'batch', 'sealed': sealed})
    class Wallet:
        status = 'UNKNOWN'
        calls = 0
        async def track(self, payment_hash, amount, fee):
            self.calls += 1
            assert payment_hash == sealed['payment_hash'] and amount == 100 and fee == 10
            return {'status': self.status, 'preimage': preimage.hex(), 'fee_msat': 2}
        async def pay(self, *args):
            pytest.fail('Recovery must never send a payment')
    wallet = Wallet()
    buyer = Buyer(identity, tmp_path, wallet)
    buyer.save('session.0.batch.json', batch)
    buyer.save('session.0.attempt.json', dict(provider=provider.public,
        batch_hash=digest(batch), commitment=digest(sealed), payment_hash=sealed['payment_hash'],
        amount_msat=100, fee_limit_msat=10))
    restarted = Buyer(identity, tmp_path, wallet)
    assert (await restarted.reconcile_payments())[0]['status'] == 'UNKNOWN'
    assert not (tmp_path / 'session.0.payment.json').exists()
    wallet.status = 'SUCCEEDED'
    assert (await restarted.reconcile_payments())[0]['status'] == 'SUCCEEDED'
    import json
    record = json.loads((tmp_path / 'session.0.payment.json').read_text())
    assert unseal(sealed, bytes.fromhex(record['preimage']))['groups'][0]['text'] == 'ok'
    assert await restarted.reconcile_payments() == []
    assert wallet.calls == 2


async def test_tracking_timeout_is_unknown(monkeypatch):
    import httpx
    wallet = object.__new__(LndRegtest)
    wallet.url, wallet.headers, wallet.tls = 'https://lnd.invalid', {}, True
    async def check():
        pass
    wallet.check_network = check
    async def fail(*args, **kwargs):
        raise httpx.ReadTimeout('uncertain result')
    monkeypatch.setattr(httpx.AsyncClient, 'send', fail)
    assert await wallet.track('a' * 64, 100, 10) == {'status': 'UNKNOWN'}


async def test_payment_intent_is_durable_before_dispatch(config, manifest, tmp_path):
    import httpx
    import json
    from offence.client import Buyer
    class ProviderWallet(WalletSimulator):
        async def wait(self, *args):
            return True
    config.offer.output_msat_per_token = 5
    app = create_app(tmp_path / 'provider', config, wallet=ProviderWallet(), background=False)
    records = tmp_path / 'buyer'
    class BuyerWallet:
        async def pay(self, invoice, payment_hash, amount, commitment, fee):
            attempts = list(records.glob('*.attempt.json'))
            assert len(attempts) == 1
            attempt = json.loads(attempts[0].read_text())
            assert attempt['payment_hash'] == payment_hash
            assert attempt['commitment'] == commitment
            assert attempt['amount_msat'] == amount
            assert attempt['invoice'] == invoice
            assert list(records.glob('*.batch.json'))
            raise httpx.ReadTimeout('payment outcome unknown')
    buyer = Buyer(Identity(), records, BuyerWallet())
    with pytest.raises(httpx.ReadTimeout):
        async for _ in buyer.run('http://provider', app.state.provider.identity.public,
                manifest.model_id, 'hello', 8, 40, allow_lab=True, total_fee_limit_msat=8000,
                transport=httpx.ASGITransport(app=app)):
            pass
    assert len(list(records.glob('*.attempt.json'))) == 1
    assert not list(records.glob('*.payment.json'))


@pytest.mark.parametrize("ending", ["\n", ""])
async def test_tracking_reads_lnd_stream(monkeypatch, ending):
    import httpx
    import json
    preimage = b'a' * 32
    payment_hash = hashlib.sha256(preimage).hexdigest()
    wallet = object.__new__(LndRegtest)
    wallet.url, wallet.headers, wallet.tls = 'https://lnd.invalid', {}, True
    async def check():
        pass
    wallet.check_network = check
    def handle(request):
        assert request.method == 'GET'
        import base64
        assert request.url.path == '/v2/router/track/' + base64.urlsafe_b64encode(bytes.fromhex(payment_hash)).decode()
        return httpx.Response(200, text=json.dumps({'result': {
            'payment_hash': payment_hash, 'value_msat': '100', 'fee_msat': '2',
            'payment_preimage': preimage.hex(), 'status': 'SUCCEEDED'}}) + ending)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        **kw, transport=httpx.MockTransport(handle)))
    assert await wallet.track(payment_hash, 100, 10) == {
        'status': 'SUCCEEDED', 'preimage': preimage.hex(), 'fee_msat': 2}


def test_mainnet_requires_explicit_assurance_and_real_backend():
    from offence.models import Config
    with pytest.raises(ValueError, match='seller-claim'):
        Config(lightning='lnd-mainnet')
    with pytest.raises(ValueError, match='Fixture'):
        Config(lightning='lnd-mainnet', allow_seller_claim=True, backend='fixture')


def test_seller_claim_quote_and_required_proof_refusal(config, manifest, tmp_path):
    from offence.protocol import ProofUnavailable
    config.allow_seller_claim = True
    app = create_app(tmp_path, config, background=False)
    p, buyer = app.state.provider, Identity()
    quote = p.quote(request(buyer, p.identity.public, manifest, proof_policy='seller-claim'))
    assert quote['body']['assurance'] == 'seller-claim'
    assert quote['body']['proof'] == 'unavailable'
    with pytest.raises(ProofUnavailable):
        p.quote(request(buyer, p.identity.public, manifest, proof_policy='required'))


def test_monetary_reservations_survive_restart_and_replay(tmp_path):
    from offence.spending import reserve
    import sqlite3
    reserve(tmp_path, 'first', 100, 10, 220)
    reserve(tmp_path, 'second', 100, 10, 220)
    with pytest.raises(ValueError, match='Daily'):
        reserve(tmp_path, 'third', 1, 0, 220)
    with pytest.raises(sqlite3.IntegrityError):
        reserve(tmp_path, 'first', 100, 10, 1000)


async def test_provider_reconciles_settlement_after_restart(config, manifest, tmp_path):
    config.offer.output_msat_per_token = 5
    class Wallet(WalletSimulator):
        async def settled(self, payment_hash, amount):
            return self.invoices[payment_hash][3].is_set()
    wallet = Wallet()
    app = create_app(tmp_path, config, wallet=wallet, background=False)
    p, buyer = app.state.provider, Identity()
    q = p.quote(request(buyer, p.identity.public, manifest, max_total_msat=40))
    accepted = buyer.sign({'type': 'accept', 'session': q['body']['session'], 'quote_hash': digest(q)})
    stream = p.stream(*p.accept(accepted))
    batch = await anext(stream)
    await stream.aclose()
    wallet.pay(batch['body']['sealed']['payment_hash'])
    p.store.close()
    restarted = create_app(tmp_path, config, wallet=wallet, background=False).state.provider
    await restarted.reconcile()
    assert restarted.store.evidence()['settled_batches'] == 1
    assert restarted.active == 0


async def test_mainnet_wallet_rejects_regtest_node():
    from offence.lightning import LndMainnet
    wallet = object.__new__(LndMainnet)
    async def call(*args):
        return {'chains': [{'chain': 'bitcoin', 'network': 'regtest'}]}
    wallet.call = call
    with pytest.raises(ValueError, match='mainnet'):
        await wallet.check_network()


def test_mainnet_rejects_lab_protocol(config, manifest, tmp_path):
    config.backend = 'none'
    config.lightning = 'lnd-mainnet'
    config.allow_seller_claim = True
    from offence.backend import Fixture
    app = create_app(tmp_path, config, backend=Fixture(), wallet=WalletSimulator(), background=False)
    p, buyer = app.state.provider, Identity()
    with pytest.raises(ValueError, match='network'):
        p.quote(request(buyer, p.identity.public, manifest, proof_policy='seller-claim'))


def test_unknown_reservations_do_not_expire_at_midnight(tmp_path, monkeypatch):
    from offence import spending
    now = 100000
    monkeypatch.setattr(spending.time, 'time', lambda: now)
    spending.reserve(tmp_path, 'uncertain', 90, 10, 100)
    now += 86401
    with pytest.raises(ValueError, match='Daily'):
        spending.reserve(tmp_path, 'next', 1, 0, 100)
    spending.complete(tmp_path, 'uncertain')
    spending.reserve(tmp_path, 'next', 1, 0, 100)
