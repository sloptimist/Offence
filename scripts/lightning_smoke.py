"""Disposable real Bitcoin/LND regtest test. No mainnet configuration or funds."""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offence.lightning import LndRegtest

BITCOIN = 'lncm/bitcoind@sha256:1d335a5adbfac6d66cee20b62b339385819dc75f8cb60c6c5773922cec4c25ef'
LND = 'lightninglabs/lnd@sha256:f0a2bdc4b8bc89cb3b31b6e12d6b16ac5145defd916d8152cf0c1c07d8697cff'
prefix = 'offence-regtest-' + secrets.token_hex(4)
containers = []

def cmd(*args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:500])
    return r.stdout.strip()

def docker(*args):
    return cmd('docker', *args)

def btc(*args):
    raw = docker('exec', prefix+'-btc', 'bitcoin-cli', '-regtest', '-rpcuser=regtest', '-rpcpassword=regtest', *args)
    try: return json.loads(raw)
    except json.JSONDecodeError: return raw

def ln(node, *args):
    return json.loads(docker('exec', prefix+'-'+node, 'lncli', '--network=regtest', *args))

def wait(fn, seconds=60):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        try:
            value = fn()
            if value: return value
        except (RuntimeError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise TimeoutError('Regtest readiness deadline exceeded')

def run(name, image, *args, ports=()):
    cname = prefix+'-'+name
    docker('run','-d','--name',cname,'--network',prefix,*ports,image,*args)
    containers.append(cname)
    return cname

async def exercise(a, b):
    await a.check_network()
    await b.check_network()
    preimage = secrets.token_bytes(32)
    payment_hash = hashlib.sha256(preimage).hexdigest()
    commitment = hashlib.sha256(b'offence regtest batch').hexdigest()
    invoice = await b.invoice(preimage, 100000, commitment, 60)
    assert not await b.settled(payment_hash, 100000)
    recovered = await a.pay(invoice,payment_hash,100000,commitment,1000)
    assert recovered == preimage
    assert await b.settled(payment_hash,100000)
    result = await a.track(payment_hash,100000,1000)
    assert result['status']=='SUCCEEDED', result
    assert result['preimage']==preimage.hex()
    # New adapter represents a buyer restart and must recover the same key.
    result = await a.track(payment_hash,100000,1000)
    assert result['status']=='SUCCEEDED'
    print('PASS: real regtest invoice, payment, provider settlement and buyer hash recovery', flush=True)
    import socket
    import uvicorn
    from offence.app import create_app
    from offence.client import Buyer
    from offence.crypto import Identity
    from offence.models import Config, Manifest, Offer
    manifest = Manifest(name='Regtest fixture', architecture='fixture', quantization='none',
        context_tokens=100, artifacts=[{'path':'fixture','sha256':'a'*64,'size':1,'role':'weights'}])
    config = Config(backend='fixture', allow_lab_unverified=True,
        offer=Offer(manifest=manifest, output_msat_per_token=5000, batch_tokens=2))
    with tempfile.TemporaryDirectory(prefix='offence-stream-') as td:
        app=create_app(Path(td)/'provider', config, wallet=b)
        sock=socket.socket()
        sock.bind(('127.0.0.1',0))
        endpoint='http://127.0.0.1:'+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        task=asyncio.create_task(server.serve(sockets=[sock]))
        try:
            for _ in range(100):
                if server.started: break
                if task.done(): await task
                await asyncio.sleep(.05)
            buyer=Buyer(Identity(),Path(td)/'buyer',a)
            text=''
            async for delta in buyer.run(endpoint,app.state.provider.identity.public,manifest.model_id,
                    'hello',8,40000,allow_lab=True,fee_limit_msat=0,total_fee_limit_msat=0):
                text+=delta
            assert text
            assert app.state.store.evidence()['settled_batches']==3
            print('PASS: Offence TCP stream paid and decrypted three real regtest batches',flush=True)
            import httpx
            class LostReply:
                network = 'regtest'
                async def pay(self, *args):
                    await a.pay(*args)
                    raise httpx.ReadTimeout('Injected loss of successful payment response')
            lost_dir=Path(td)/'lost-reply'
            lost=Buyer(Identity(),lost_dir,LostReply())
            try:
                async for _ in lost.run(endpoint,app.state.provider.identity.public,manifest.model_id,
                        'hello',8,40000,allow_lab=True,fee_limit_msat=0,total_fee_limit_msat=0):
                    pass
                raise AssertionError('Injected interruption was not observed')
            except httpx.ReadTimeout:
                pass
            restarted=Buyer(lost.identity,lost_dir,a)
            outcomes=await restarted.reconcile_payments()
            assert outcomes and outcomes[0]['status']=='SUCCEEDED'
            assert len(list(lost_dir.glob('*.payment.json')))==1
            await app.state.provider.reconcile()
            print('PASS: lost successful payment reply recovered from durable intent without resending',flush=True)
            class HostedRegtest:
                # Real regtest receiver chooses the payment preimage, as a hosted
                # wallet would. This is not a live Strike API test.
                network = 'regtest'
                settlement_mode = 'provider-key-v1'
                async def check_network(self): await b.check_network()
                async def settled(self, *args): return await b.settled(*args)
                async def create_batch_invoice(self, amount, commitment, expiry):
                    secret=secrets.token_bytes(32)
                    ph=hashlib.sha256(secret).hexdigest()
                    invoice=await b.invoice(secret,amount,commitment,expiry)
                    return {'invoice':invoice,'payment_hash':ph,'reference':{'hash':ph}}
                async def settled_batch(self, reference, payment_hash, amount):
                    assert reference['hash']==payment_hash
                    return await b.settled(payment_hash,amount)
            app.state.provider.wallet=HostedRegtest()
            hosted=Buyer(Identity(),Path(td)/'hosted',a)
            output=[x async for x in hosted.run(endpoint,app.state.provider.identity.public,manifest.model_id,
                'hello',8,40000,allow_lab=True,fee_limit_msat=0,total_fee_limit_msat=0,allow_provider_key_release=True)]
            assert ''.join(output)=='This is a lab fixture.'
            assert len(list(hosted.directory.glob('*.key.json')))==3
            print('PASS: supplier-key settlement over TCP with three real regtest payments',flush=True)
            interrupted=Buyer(Identity(),Path(td)/'hosted-lost',LostReply())
            try:
                async for _ in interrupted.run(endpoint,app.state.provider.identity.public,manifest.model_id,
                    'hello',8,40000,allow_lab=True,fee_limit_msat=0,total_fee_limit_msat=0,allow_provider_key_release=True): pass
                raise AssertionError('Missing injected hosted interruption')
            except httpx.ReadTimeout: pass
            restarted=Buyer(interrupted.identity,interrupted.directory,a)
            outcomes=await restarted.reconcile_payments()
            assert outcomes[0]['status']=='SUCCEEDED'
            recovered=await restarted.recover_hosted_keys(endpoint,app.state.provider.identity.public)
            assert recovered[0]['text']=='This is '
            print('PASS: hosted key recovery after lost payment reply without a second payment',flush=True)

        finally:
            server.should_exit=True
            await task
            sock.close()


try:
    docker('network','create',prefix)
    run('btc',BITCOIN,'-regtest','-server','-rpcbind=0.0.0.0','-rpcallowip=0.0.0.0/0',
        '-rpcuser=regtest','-rpcpassword=regtest','-fallbackfee=0.0002',
        '-zmqpubrawblock=tcp://0.0.0.0:28332','-zmqpubrawtx=tcp://0.0.0.0:28333')
    wait(lambda: btc('getblockchaininfo'))
    btc('createwallet','miner')
    address=btc('getnewaddress')
    btc('generatetoaddress','101',address)
    for name in ['a','b']:
        run(name,LND,'--bitcoin.regtest','--bitcoin.node=bitcoind',
            '--bitcoind.rpchost='+prefix+'-btc:18443','--bitcoind.rpcuser=regtest','--bitcoind.rpcpass=regtest',
            '--bitcoind.zmqpubrawblock=tcp://'+prefix+'-btc:28332',
            '--bitcoind.zmqpubrawtx=tcp://'+prefix+'-btc:28333','--noseedbackup',
            '--restlisten=0.0.0.0:8080','--tlsextraip=127.0.0.1', ports=('-p','127.0.0.1::8080'))
        wait(lambda: ln(name,'getinfo').get('synced_to_chain'))
    funding=ln('a','newaddress','p2wkh')['address']
    btc('sendtoaddress',funding,'1')
    btc('generatetoaddress','6',address)
    wait(lambda: int(ln('a','walletbalance')['confirmed_balance']) > 0)
    pub=ln('b','getinfo')['identity_pubkey']
    ln('a','connect',pub+'@'+prefix+'-b:9735')
    ln('a','openchannel','--node_key='+pub,'--local_amt=500000','--sat_per_vbyte=2')
    btc('generatetoaddress','6',address)
    wait(lambda: any(c['active'] for c in ln('a','listchannels')['channels']))
    wait(lambda: any(c['active'] for c in ln('b','listchannels')['channels']))
    wait(lambda: len(ln('a','describegraph')['edges']) > 0)
    print('Regtest channel active',flush=True)
    with tempfile.TemporaryDirectory(prefix='offence-lnd-') as td:
        wallets=[]
        for name in ['a','b']:
            root=Path(td)/name
            root.mkdir(mode=0o700)
            docker('cp',prefix+'-'+name+':/root/.lnd/tls.cert',str(root/'tls.cert'))
            docker('cp',prefix+'-'+name+':/root/.lnd/data/chain/bitcoin/regtest/admin.macaroon',str(root/'wallet.macaroon'))
            (root/'wallet.macaroon').chmod(0o600)
            port=docker('port',prefix+'-'+name,'8080/tcp').split(':')[-1]
            wallets.append(LndRegtest('https://127.0.0.1:'+port,root/'wallet.macaroon',root/'tls.cert'))
        asyncio.run(exercise(*wallets))
finally:
    for name in reversed(containers):
        subprocess.run(['docker','rm','-f',name],capture_output=True)
    subprocess.run(['docker','network','rm',prefix],capture_output=True)
