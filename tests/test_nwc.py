"""Wallet boundary tests. No real funds or remote wallet required."""
import hashlib
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest
from nostr_sdk import Method, TransactionType

from offence.buyer_app import BuyerSettings, create_buyer_app
from offence.nwc import NwcWallet, validate_connection

# Public test key material only, never funded.
CONNECTION = 'nostr+walletconnect://' + '79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798' + '?relay=wss%3A%2F%2Frelay.example&secret=' + '0'*63+'1'
PREIMAGE = bytes(range(32))
HASH = hashlib.sha256(PREIMAGE).hexdigest()


class SDK:
    def __init__(self):
        self.calls = 0
        self.network = 'mainnet'
        self.methods = [Method.GET_INFO(), Method.PAY_INVOICE(), Method.LOOKUP_INVOICE()]
        self.result = NS(preimage=PREIMAGE.hex(), fees_paid=9000, amount=1000,
                         transaction_type=TransactionType.OUTGOING, payment_hash=HASH, settled_at=123)
    async def get_info(self): return NS(network=self.network, methods=self.methods)
    async def pay_invoice(self, request):
        self.calls += 1
        if self.result is None: raise TimeoutError()
        return self.result
    async def lookup_invoice(self, request):
        if self.result is None: raise TimeoutError()
        return self.result


@pytest.mark.parametrize('change', [lambda x:x.replace('wss%3A','ws%3A'), lambda x:x+'&secret=1',
    lambda x:x.replace('nostr+walletconnect:', 'https:'),lambda x:x+'#fragment',lambda x:x+'&unknown=1'])
def test_invalid_connection(change):
    with pytest.raises(ValueError): validate_connection(change(CONNECTION))


async def test_permissions_network_invoice_and_single_send(monkeypatch):
    sdk=SDK(); wallet=NwcWallet(CONNECTION, client=sdk)
    await wallet.check_network()
    sdk.network='regtest'
    with pytest.raises(ValueError): await wallet.check_network()
    sdk.network='mainnet'; sdk.methods.pop()
    with pytest.raises(ValueError): await wallet.check_network()
    sdk.methods.append(Method.LOOKUP_INVOICE())
    decoded={'payment_hash':HASH,'amount_msat':1000,'description_hash':'a'*64,'expires':10**12}
    monkeypatch.setattr('offence.nwc.decode_invoice',lambda _: decoded)
    for args in [(HASH,1001,'a'*64,0),(HASH,1000,'b'*64,0),(HASH,1000,'a'*64,1)]:
        with pytest.raises(ValueError): await wallet.pay('invoice',*args)
    assert sdk.calls==0
    assert await wallet.pay('invoice',HASH,1000,'a'*64,0)==PREIMAGE
    assert sdk.calls==1
    sdk.result=None
    with pytest.raises(TimeoutError): await wallet.pay('invoice',HASH,1000,'a'*64,0)
    assert sdk.calls==2
    assert await wallet.track(HASH,1000,0)=={'status':'UNKNOWN'}
    assert sdk.calls==2


async def test_recovery_accepts_wallet_fees_but_not_wrong_payment():
    sdk=SDK(); wallet=NwcWallet(CONNECTION,client=sdk)
    assert await wallet.track(HASH,1000,0)=={'status':'SUCCEEDED','preimage':PREIMAGE.hex(),'fee_msat':9000}
    sdk.result.amount=1001
    with pytest.raises(ValueError): await wallet.track(HASH,1000,0)
    sdk.result.amount=1000; sdk.result.preimage='0'*64
    with pytest.raises(ValueError): await wallet.track(HASH,1000,0)
    sdk.result.preimage=None
    assert await wallet.track(HASH,1000,0)=={'status':'UNKNOWN'}


def test_no_fake_local_fee_guarantee():
    with pytest.raises(ValueError): BuyerSettings(wallet='nwc-mainnet',assurance='seller-claim')
    with pytest.raises(ValueError): BuyerSettings(wallet='nwc-mainnet',assurance='seller-claim',wallet_managed_fees=True,fee_per_batch_msat=1)
    settings=BuyerSettings(wallet='nwc-mainnet',assurance='seller-claim',wallet_managed_fees=True)
    assert settings.network=='offence-v1'


async def test_owner_only_connect_pause_and_secret_storage(tmp_path):
    class Wallet:
        network='mainnet'
        async def check_network(self): pass
        async def close(self): pass
    app=create_buyer_app(tmp_path,background=False,wallet_factory=lambda _: Wallet())
    owner={'Authorization':'Bearer '+(tmp_path/'owner.key').read_text()}
    agent={'Authorization':'Bearer '+(tmp_path/'agent.key').read_text()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8787') as c:
        assert (await c.post('/admin/wallet/connect',headers=agent,json={'connection':CONNECTION})).status_code==401
        r=await c.post('/admin/wallet/connect',headers=owner,json={'connection':CONNECTION})
        assert r.status_code==200,r.text
        assert not r.json()['spending_enabled']
        assert (tmp_path/'wallet.nwc').read_text()==CONNECTION
        assert (tmp_path/'wallet.nwc').stat().st_mode & 0o777 == 0o600
        s=(await c.get('/admin/state',headers=owner))
        assert CONNECTION not in s.text and 'secret=' not in s.text
        policy=s.json()['settings']
        policy.update(wallet='nwc-mainnet',assurance='seller-claim',wallet_managed_fees=True,
                      max_price_msat=1,request_limit_msat=100,daily_limit_msat=200)
        assert (await c.put('/admin/settings',headers=owner,json=policy)).status_code==200
        assert (await c.post('/admin/wallet/connect',headers=owner,json={'connection':CONNECTION})).status_code==409
        assert (await c.post('/admin/wallet/disconnect',headers=agent,json={})).status_code==401
        assert (await c.post('/admin/wallet/disconnect',headers=owner,json={})).status_code==200
        assert not (tmp_path/'wallet.nwc').exists()
        s=(await c.get('/admin/state',headers=owner)).json()
        assert s['settings']['wallet']=='disabled' and s['settings']['daily_limit_msat']==0
    app.state.store.close()


async def test_disconnect_preserves_uncertain_payment_credentials(tmp_path):
    app=create_buyer_app(tmp_path,background=False)
    (tmp_path/'wallet.nwc').write_text(CONNECTION)
    (tmp_path/'purchases/test.attempt.json').write_text('{}')
    owner={'Authorization':'Bearer '+(tmp_path/'owner.key').read_text()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8787') as c:
        r=await c.post('/admin/wallet/disconnect',headers=owner,json={})
        assert r.json()['credential_retained_for_recovery']
        assert (tmp_path/'wallet.nwc').exists()
        changed=CONNECTION[:-1]+'2'
        assert (await c.post('/admin/wallet/connect',headers=owner,json={'connection':changed})).status_code==409
    app.state.store.close()
