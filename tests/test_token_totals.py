import json
import time

import httpx
import pytest

from offence.app import create_app
from offence.client import Buyer
from offence.crypto import Identity, digest
from conftest import request
from test_payments import WalletSimulator


async def test_served_tokens_count_receipts_once_and_survive_cleanup(config, manifest, tmp_path):
    node = tmp_path / 'node'
    app = create_app(node, config, background=False)
    buyer = Buyer(Identity(), tmp_path / 'buyer')
    p = app.state.provider
    output = [s async for s in buyer.run('http://node', p.identity.public, manifest.model_id,
        'hello', 8, 0, allow_lab=True, transport=httpx.ASGITransport(app=app))]
    assert ''.join(output) == 'This is a lab fixture.'
    totals = p.store.token_totals()
    assert totals['served_tokens'] == 5 and totals['paid_tokens'] == 0
    assert totals['models'][0]['model_id'] == manifest.model_id
    for path in buyer.directory.glob('*.receipt.json'):
        p.store.receipt(json.loads(path.read_text()))
    assert p.store.token_totals() == totals
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://node') as c:
        assert (await c.get('/v1/status')).json()['token_totals'] == totals
    with p.store.db:
        p.store.db.execute('UPDATE sessions SET created=?', (int(time.time()) - 8*86400,))
    p.store.cleanup()
    assert p.store.evidence()['buyer_receipts'] == 0
    p.store.close()
    restarted = create_app(node, config, background=False)
    assert restarted.state.store.token_totals() == totals


async def test_unacknowledged_generated_output_is_not_served(config, manifest, tmp_path):
    p = create_app(tmp_path, config, background=False).state.provider
    buyer = Identity()
    q = p.quote(request(buyer, p.identity.public, manifest))
    accept = buyer.sign({'type':'accept','session':q['body']['session'],'quote_hash':digest(q)})
    stream = p.stream(*p.accept(accept))
    await anext(stream)
    await stream.aclose()
    assert p.store.token_totals()['served_tokens'] == 0


async def test_paid_counts_are_idempotent_and_migrate_once(config, manifest, tmp_path):
    class PaidWallet(WalletSimulator):
        async def wait(self, *args): return True
    config.offer.output_msat_per_token = 5
    p = create_app(tmp_path, config, wallet=PaidWallet(), background=False).state.provider
    buyer = Identity()
    q = p.quote(request(buyer, p.identity.public, manifest, max_total_msat=40))
    sid=q['body']['session']
    accept=buyer.sign({'type':'accept','session':sid,'quote_hash':digest(q)})
    _=[m async for m in p.stream(*p.accept(accept))]
    p.store.paid(sid, 0)
    assert p.store.token_totals()['paid_tokens'] == 5
    assert p.store.token_totals()['served_tokens'] == 0
    # Simulate a pre-tracker database with retained settlement evidence.
    with p.store.db:
        p.store.db.execute('DROP TABLE token_totals')
        p.store.db.execute("DELETE FROM meta WHERE key='token_tracker_started'")
    p.store.close()
    for _ in range(2):
        p=create_app(tmp_path, config, wallet=PaidWallet(), background=False).state.provider
        assert p.store.token_totals()['paid_tokens'] == 5
        p.store.close()
