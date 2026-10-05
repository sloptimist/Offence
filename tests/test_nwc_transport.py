"""Exercise the pinned SDK's signed, encrypted NWC exchange on a local test relay."""
import asyncio
from datetime import timedelta
import hashlib
import json
from urllib.parse import quote

import pytest
import nostr_sdk as n
from websockets.asyncio.server import serve

from offence.nwc import NwcWallet


async def test_sdk_encrypted_connection_and_recovery():
    wallet_keys=n.Keys.parse('0'*63+'1')
    buyer_keys=n.Keys.parse('0'*63+'2')
    preimage=bytes(range(32)); payment_hash=hashlib.sha256(preimage).hexdigest()
    requests=[]; records=[]
    def signed(kind,content,tags):
        event=n.EventBuilder(n.Kind(kind),content).tags([n.Tag.parse(t) for t in tags])
        return json.loads(wallet_keys.sign_event(event.finalize_unsigned(wallet_keys.public_key())).as_json())
    info=signed(13194,'get_info pay_invoice lookup_invoice',[['encryption','nip44_v2']])
    records.append(info)
    def matches(event,filters):
        return any(all((key=='authors' and event['pubkey'] in values) or
                       (key=='kinds' and event['kind'] in values) or
                       (key.startswith('#') and any(t[0]==key[1:] and t[1] in values for t in event['tags']))
                       or key in ('limit','since','until') for key,values in f.items()) for f in filters)
    async def relay(ws):
        subscriptions={}
        async for raw in ws:
            msg=json.loads(raw)
            if msg[0]=='REQ':
                subscriptions[msg[1]]=msg[2:]
                for event in records:
                    if matches(event,msg[2:]): await ws.send(json.dumps(['EVENT',msg[1],event]))
                await ws.send(json.dumps(['EOSE',msg[1]]))
            elif msg[0]=='CLOSE': subscriptions.pop(msg[1],None)
            elif msg[0]=='EVENT':
                event=n.Event.from_json(json.dumps(msg[1]))
                assert event.verify()
                assert event.author()==buyer_keys.public_key()
                body=json.loads(n.nip44_decrypt(wallet_keys.secret_key(),buyer_keys.public_key(),event.content()))
                requests.append(body['method'])
                if body['method']=='get_info':
                    result={'network':'mainnet','methods':['get_info','pay_invoice','lookup_invoice']}
                elif body['method']=='lookup_invoice':
                    assert body['params']['payment_hash']==payment_hash
                    result={'type':'outgoing','state':'settled','payment_hash':payment_hash,
                            'amount':1000,'fees_paid':27,'preimage':preimage.hex(),
                            'created_at':1700000000,'settled_at':1700000001}
                else:
                    raise AssertionError('This test must not send a payment')
                encrypted=n.nip44_encrypt(wallet_keys.secret_key(),buyer_keys.public_key(),
                    json.dumps({'result_type':body['method'],'result':result}),n.Nip44Version.V2)
                response=signed(23195,encrypted,[['p',buyer_keys.public_key().to_hex()],['e',event.id().to_hex()]])
                records.append(response)
                await ws.send(json.dumps(['OK',event.id().to_hex(),True,'']))
                for sub,filters in subscriptions.items():
                    if matches(response,filters): await ws.send(json.dumps(['EVENT',sub,response]))
    async with serve(relay,'127.0.0.1',0) as server:
        port=server.sockets[0].getsockname()[1]
        # Only this SDK test uses plaintext loopback. Production rejects ws://.
        uri='nostr+walletconnect://'+wallet_keys.public_key().to_hex()+'?relay='+quote(f'ws://127.0.0.1:{port}',safe='')+'&secret='+'0'*63+'2'
        sdk=n.NostrWalletConnectBuilder(n.NostrWalletConnectUri.parse(uri)).timeout(timedelta(seconds=3)).build()
        adapter=NwcWallet(uri.replace('ws%3A','wss%3A'),client=sdk)
        try:
            async with asyncio.timeout(15):
                await adapter.check_network()
                recovered=await adapter.track(payment_hash,1000,0)
                assert recovered=={'status':'SUCCEEDED','preimage':preimage.hex(),'fee_msat':27}
        finally:
            await adapter.close()
    assert requests==['get_info','lookup_invoice']
