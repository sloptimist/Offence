"""Real TCP multi-provider job test. Synthetic models, no GPU, wallet or live service."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
import uvicorn
from offence.app import create_app
from offence.models import Config, Manifest, Offer, GatewayConfig, RoutingPolicy, Advertisement
from scripts.smoke import port


class Backend:
    def __init__(self,label):self.label,self.contexts=label,[]
    async def stream_chat(self,messages,max_tokens):
        self.contexts.append(messages)
        await asyncio.sleep(.05)
        yield {'token_ids':[1,2],'text':self.label}


async def main():
    with tempfile.TemporaryDirectory(prefix='offence-jobs-') as directory:
        root=Path(directory)
        ports=[port() for _ in range(3)]
        urls=[f'http://127.0.0.1:{p}' for p in ports]
        key=secrets.token_hex(32)
        os.environ['OFFENCE_GATEWAY_API_KEY']=key
        model=Manifest(name='Job contract fixture',architecture='fixture',quantization='none',context_tokens=4096,
            artifacts=[{'path':'fixture.txt','size':0,'sha256':'0'*64,'role':'weights'}])
        backends=[Backend('result A'),Backend('result B')]
        provider_cfg=Config(backend='fixture',allow_lab_unverified=True,
                            offer=Offer(manifest=model,output_msat_per_token=0,batch_tokens=2))
        apps=[create_app(root/f'p{i}',provider_cfg.model_copy(deep=True),backend=backends[i],background=False) for i in range(2)]
        cfg=Config(allowed_private_peers=urls[:2],gateway=GatewayConfig(allow_free_lab=True,
                   policies=[RoutingPolicy(alias='balanced',model_ids=[model.model_id])]))
        apps.append(create_app(root/'buyer',cfg,background=False))
        for i in range(2):
            provider=apps[i].state.provider
            ad=Advertisement(issued=int(time.time()),expires=int(time.time())+180,sequence=1,endpoint=urls[i],
                             offer=provider_cfg.offer.model_copy(update={'text_chat':True}))
            apps[2].state.store.ingest(provider.identity.sign(ad.model_dump()))
        servers=[uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=p,log_level='error')) for app,p in zip(apps,ports)]
        tasks=[asyncio.create_task(s.serve()) for s in servers]
        try:
            async with httpx.AsyncClient(base_url=urls[2],headers={'Authorization':'Bearer '+key},trust_env=False,timeout=10) as client:
                for _ in range(100):
                    if all(s.started for s in servers):break
                    await asyncio.sleep(.05)
                payload={'idempotency_key':'tcp_job_0000000001','tasks':[
                    {'id':'a','model':'balanced','messages':[{'role':'user','content':'only context A'}],'max_tokens':8},
                    {'id':'b','model':'balanced','messages':[{'role':'user','content':'only context B'}],'max_tokens':8}],
                    'max_total_output_tokens':16,'proof_policy':'lab-unverified'}
                response=await client.post('/v1/jobs',json=payload)
                assert response.status_code==202,response.text
                jid=response.json()['id']
                for _ in range(100):
                    result=(await client.get('/v1/jobs/'+jid)).json()
                    if result['state'] not in {'queued','running'}:break
                    await asyncio.sleep(.05)
                assert result['state']=='complete',result
                assert len({t['attempts'][0]['provider'] for t in result['tasks']})==2,result
                assert all(t['attempts'][0]['session'] for t in result['tasks'])
                assert sorted(c[0]['content'] for b in backends for c in b.contexts)==['only context A','only context B']
                repeat=await client.post('/v1/jobs',json=payload)
                assert repeat.json()['id']==jid and sum(len(b.contexts) for b in backends)==2
                assert result['spent_msat']==0 and result['received_output_tokens']==4
                assert all(apps[i].state.provider.active==0 for i in range(2))
            print(json.dumps({'tcp_multi_provider_job':'passed','independent_contexts':'passed',
                'idempotency':'passed','signed_delivery_records':'passed','payments':'disabled','backend':'fixture'}))
        finally:
            for server in servers:server.should_exit=True
            await asyncio.gather(*tasks)


if __name__=='__main__':asyncio.run(main())
