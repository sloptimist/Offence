import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx
import pytest

from offence.app import create_app
from offence.client import Buyer
from offence.crypto import Identity, digest, unseal, unb64
from conftest import request


class HostedWallet:
    network = 'regtest'
    settlement_mode = 'provider-key-v1'

    def __init__(self, auto=False):
        self.items = {}
        self.auto = auto
        self.payments = 0

    async def check_network(self): pass

    async def create_batch_invoice(self, amount, commitment, expiry):
        secret = hashlib.sha256(str(len(self.items)).encode()).digest()
        ph = hashlib.sha256(secret).hexdigest()
        self.items[ph] = {'preimage':secret,'amount':amount,'commitment':commitment,'paid':self.auto}
        return {'invoice':'test:'+ph,'payment_hash':ph,'reference':{'hash':ph}}

    async def settled_batch(self, reference, payment_hash, amount):
        assert reference['hash'] == payment_hash
        assert self.items[payment_hash]['amount'] == amount
        return self.items[payment_hash]['paid']

    async def pay(self, invoice, payment_hash, amount, commitment, fee):
        item = self.items[payment_hash]
        assert invoice == 'test:'+payment_hash and item['amount']==amount and item['commitment']==commitment
        item['paid'] = True
        self.payments += 1
        return item['preimage']

    async def track(self, payment_hash, amount, fee):
        return {'status':'SUCCEEDED','preimage':self.items[payment_hash]['preimage'].hex(),'fee_msat':0}


def accepted(p, manifest, buyer):
    q=p.quote(request(buyer,p.identity.public,manifest,max_total_msat=40,allow_provider_key_release=True))
    a=buyer.sign({'type':'accept','session':q['body']['session'],'quote_hash':digest(q)})
    return q,p.stream(*p.accept(a))


def release(buyer,batch,secret):
    h=batch['body']['sealed']['header']
    return buyer.sign({'type':'release-key','session':h['session'],'sequence':h['sequence'],
        'batch_hash':digest(batch),'payment_preimage':secret.hex(),'issued':int(time.time())})


async def test_hosted_requires_opt_in_and_withholds_keys_until_credit(config,manifest,tmp_path):
    config.offer.output_msat_per_token=5
    wallet=HostedWallet()
    p=create_app(tmp_path,config,wallet=wallet,background=False).state.provider
    buyer=Identity()
    with pytest.raises(ValueError,match='explicitly accept'):
        p.quote(request(buyer,p.identity.public,manifest,max_total_msat=40))
    q,stream=accepted(p,manifest,buyer)
    batch=await anext(stream)
    assert batch['body']['free_key'] is None
    ph=batch['body']['invoice_payment_hash']
    secret=wallet.items[ph]['preimage']
    assert ph != batch['body']['sealed']['payment_hash']
    with pytest.raises(ValueError,match='confirmed credited'):
        await p.release_key(release(buyer,batch,secret))
    with pytest.raises(ValueError,match='buyer mismatch'):
        await p.release_key(release(Identity(),batch,secret))
    with pytest.raises(ValueError,match='payment proof'):
        await p.release_key(release(buyer,batch,b'wrong'.ljust(32,b'!')))
    wallet.items[ph]['paid']=True
    result=await p.release_key(release(buyer,batch,secret))
    assert unseal(batch['body']['sealed'],unb64(result['body']['key']))['groups']
    await p.release_key(release(buyer,batch,secret))
    assert p.store.token_totals()['paid_tokens']==2
    await stream.aclose()


async def test_hosted_restart_retention_and_recovery_never_repay(config,manifest,tmp_path):
    config.offer.output_msat_per_token=5
    wallet=HostedWallet()
    app=create_app(tmp_path/'node',config,wallet=wallet,background=False)
    p=app.state.provider
    buyer=Buyer(Identity(),tmp_path/'buyer',wallet)
    q,stream=accepted(p,manifest,buyer.identity)
    batch=await anext(stream)
    ph=batch['body']['invoice_payment_hash'];h=batch['body']['sealed']['header'];name=f"{h['session']}.0"
    buyer.save(name+'.batch.json',batch)
    buyer.save(name+'.attempt.json',{'network':'regtest','provider':p.identity.public,
        'batch_hash':digest(batch),'commitment':digest(batch['body']['sealed']),
        'payment_hash':ph,'amount_msat':10,'fee_limit_msat':0})
    wallet.items[ph]['paid']=True
    await stream.aclose()
    with p.store.db:
        p.store.db.execute('UPDATE sessions SET created=?',(int(time.time())-30*86400,))
    p.store.cleanup()
    assert p.store.recover(h['session'],buyer.identity.public)['batches']
    p.store.close()
    restarted=create_app(tmp_path/'node',config,wallet=wallet,background=False)
    await restarted.state.provider.reconcile()
    assert restarted.state.store.token_totals()['paid_tokens']==2
    await buyer.reconcile_payments()
    recovered=await buyer.recover_hosted_keys('http://node',p.identity.public,transport=httpx.ASGITransport(app=restarted))
    assert recovered[0]['text']=='This is '
    assert restarted.state.store.token_totals()['served_tokens']==2
    await buyer.recover_hosted_keys('http://node',p.identity.public,transport=httpx.ASGITransport(app=restarted))
    assert restarted.state.store.token_totals()['served_tokens']==2
    assert wallet.payments==0
    evidence=restarted.state.store.evidence_packages()
    assert 'batch-key' not in json.dumps(evidence)
    assert restarted.state.store.hosted_batch(h['session'],0)['key'] not in json.dumps(evidence)


async def test_hosted_buyer_roundtrip_and_default_refusal(config,manifest,tmp_path):
    config.offer.output_msat_per_token=5
    # ASGI buffers a complete response. Auto-credit avoids a simulated transport
    # deadlock; separate provider tests exercise withheld settlement.
    wallet=HostedWallet(auto=True)
    app=create_app(tmp_path/'node',config,wallet=wallet,background=False)
    p=app.state.provider;buyer=Buyer(Identity(),tmp_path/'buyer',wallet)
    output=[x async for x in buyer.run('http://node',p.identity.public,manifest.model_id,'hello',8,40,
        allow_lab=True,fee_limit_msat=0,transport=httpx.ASGITransport(app=app),allow_provider_key_release=True)]
    assert ''.join(output)=='This is a lab fixture.'
    assert p.store.token_totals()['served_tokens']==5
    assert p.store.token_totals()['paid_tokens']==5
    assert wallet.payments==3
