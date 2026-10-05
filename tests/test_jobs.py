import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from offence.app import create_app, bounded_body
from offence.backend import Fixture
from offence.crypto import Identity, digest
from offence.gateway import install_gateway
from offence.jobs import JobRequest
from offence.models import Config, GatewayConfig, RoutingPolicy, Advertisement
from offence.store import Store


class ChatBackend(Fixture):
    def __init__(self, label):
        self.label, self.seen = label, []
    async def stream_chat(self,messages,max_tokens):
        self.seen.append(messages)
        yield {'token_ids':[1],'text':self.label}


@pytest.fixture
async def network(tmp_path,config,manifest,monkeypatch):
    monkeypatch.setenv('OFFENCE_GATEWAY_API_KEY','k'*32)
    backends=[ChatBackend('one'),ChatBackend('two')]
    apps=[create_app(tmp_path/f'p{i}',config.model_copy(deep=True),backend=backends[i],background=False) for i in range(2)]
    providers=[a.state.provider for a in apps]
    cfg=Config(allowed_private_peers=['http://p0','http://p1'],gateway=GatewayConfig(allow_free_lab=True,
        policies=[RoutingPolicy(alias='auto',model_ids=[manifest.model_id])]))
    store=Store(tmp_path/'buyer.sqlite')
    for i,p in enumerate(providers):
        ad=Advertisement(issued=int(time.time()),expires=int(time.time())+180,sequence=1,endpoint=f'http://p{i}',
                         offer=config.offer.model_copy(update={'text_chat':True}))
        store.ingest(p.identity.sign(ad.model_dump()))
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            index=int(request.url.host[-1])
            return await httpx.ASGITransport(app=apps[index]).handle_async_request(request)
    app=FastAPI()
    install_gateway(app,cfg,Identity(),store,tmp_path/'records',bounded_body,transport=Transport())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://buyer',
                                headers={'Authorization':'Bearer '+'k'*32}) as client:
        yield client,app.state.jobs,app.state.router,store,cfg,providers,backends
    await app.state.jobs.shutdown()
    store.close()
    for a in apps: a.state.store.close()


def job(**changes):
    return {'idempotency_key':'job_key_000000001','tasks':[
        {'id':'a','model':'auto','messages':[{'role':'user','content':'private context A'}],'max_tokens':4},
        {'id':'b','model':'auto','messages':[{'role':'user','content':'private context B'}],'max_tokens':4}],
        'max_total_output_tokens':8,'proof_policy':'lab-unverified',**changes}


async def finished(client,jid):
    for _ in range(200):
        result=(await client.get('/v1/jobs/'+jid)).json()
        if result['state'] not in {'queued','running'}: return result
        await asyncio.sleep(.01)
    raise AssertionError('Job did not finish')


async def test_split_job_routes_independent_context_and_records(network):
    client,manager,router,store,cfg,providers,backends=network
    response=await client.post('/v1/jobs',json=job())
    assert response.status_code==202,response.text
    result=await finished(client,response.json()['id'])
    assert result['state']=='complete' and result['spent_msat']==0
    assert result['attempted_output_tokens']==8 and result['received_output_tokens']==2
    assert len({t['attempts'][0]['provider'] for t in result['tasks']})==2
    assert all(t['attempts'][0]['session'] for t in result['tasks'])
    assert sorted([messages[0]['content'] for b in backends for messages in b.seen])==['private context A','private context B']
    assert all(len(messages)==1 for b in backends for messages in b.seen)
    assert not manager.slots.active and all(p.active==0 for p in providers)


async def test_idempotency_never_repeats_compute_and_conflict_rejected(network):
    client,manager,router,store,cfg,providers,backends=network
    original=(await client.post('/v1/jobs',json=job())).json()
    await finished(client,original['id'])
    again=await client.post('/v1/jobs',json=job())
    assert again.json()['id']==original['id']
    assert sum(len(b.seen) for b in backends)==2
    assert (await client.post('/v1/jobs',json=job(max_parallel=1))).status_code==409
    assert store.db.execute('SELECT count(*) FROM gateway_budget').fetchone()[0]==1


async def test_auth_proof_gate_and_nonzero_budget_fail_before_dispatch(network):
    client,manager,router,store,cfg,providers,backends=network
    assert (await client.post('/v1/jobs',json=job(),headers={'Authorization':''})).status_code==401
    assert (await client.post('/v1/jobs',json=job(proof_policy='required'))).status_code==412
    assert (await client.post('/v1/jobs',json=job(max_total_msat=1))).status_code==400
    assert (await client.post('/v1/jobs',json=job(max_total_output_tokens=7))).status_code==400
    assert not any(b.seen for b in backends)


async def test_trusted_policy_never_relaxes_to_other_providers(network):
    client,manager,router,store,cfg,providers,backends=network
    policy=cfg.gateway.policies[0]
    policy.privacy='trusted-only';policy.trusted_providers=[providers[0].identity.public]
    result=await finished(client,(await client.post('/v1/jobs',json=job())).json()['id'])
    assert result['state']=='complete'
    assert all(t['attempts'][0]['provider']==providers[0].identity.public for t in result['tasks'])
    assert not backends[1].seen
    policy.trusted_providers=['0'*64]
    assert (await client.post('/v1/jobs',json=job(idempotency_key='job_key_000000002'))).status_code==409


async def test_retry_uses_distinct_provider_and_shared_reserved_budget(network):
    client,manager,router,store,cfg,providers,backends=network
    first=router.select('auto',4).provider
    index=next(i for i,p in enumerate(providers) if p.identity.public==first)
    class Broken:
        async def stream_chat(self,*args):
            raise RuntimeError('fail before delivery')
            yield {}
    providers[index].backend=Broken()
    payload=job(tasks=job()['tasks'][:1],max_total_output_tokens=8,max_retries=1)
    result=await finished(client,(await client.post('/v1/jobs',json=payload)).json()['id'])
    assert result['state']=='complete',result
    assert len(result['tasks'][0]['attempts'])==2
    assert len({a['provider'] for a in result['tasks'][0]['attempts']})==2
    assert result['attempted_output_tokens']==8


async def test_partial_delivery_is_not_replayed(network):
    client,manager,router,store,cfg,providers,backends=network
    first=router.select('auto',4).provider
    index=next(i for i,p in enumerate(providers) if p.identity.public==first)
    class Partial:
        async def stream_chat(self,*args):
            yield {'token_ids':[1,2],'text':'partial'}
            raise RuntimeError('failed after delivery')
    providers[index].backend=Partial()
    payload=job(tasks=job()['tasks'][:1],max_total_output_tokens=8,max_retries=1)
    result=await finished(client,(await client.post('/v1/jobs',json=payload)).json()['id'])
    assert result['state']=='partial' and result['tasks'][0]['text']=='partial'
    assert len(result['tasks'][0]['attempts'])==1
    assert result['received_output_tokens']==2


async def test_cancel_closes_streams_and_retains_budget(network):
    client,manager,router,store,cfg,providers,backends=network
    entered=asyncio.Event();closed=[]
    class Slow:
        async def stream_chat(self,*args):
            try:
                entered.set();await asyncio.Event().wait();yield {}
            finally:closed.append(True)
    for p in providers:p.backend=Slow()
    jid=(await client.post('/v1/jobs',json=job())).json()['id']
    await asyncio.wait_for(entered.wait(),2)
    response=await client.post('/v1/jobs/'+jid+'/cancel')
    assert response.json()['state']=='cancelled'
    assert closed and not manager.slots.active and all(p.active==0 for p in providers)
    assert store.db.execute('SELECT sum(tokens) FROM gateway_budget').fetchone()[0]==8


async def test_deadline_and_immediate_cancellation(network):
    client,manager,router,store,cfg,providers,backends=network
    req=JobRequest.model_validate(job())
    result=manager.submit(req)
    await manager.cancel(result['id'])
    assert store.job(result['id'])[1]['state']=='cancelled'
    assert not manager.running
    class Slow:
        async def stream_chat(self,*args):
            await asyncio.Event().wait();yield {}
    for p in providers:p.backend=Slow()
    payload=job(idempotency_key='job_key_000000002',deadline_s=1)
    result=await finished(client,(await client.post('/v1/jobs',json=payload)).json()['id'])
    assert result['state']=='timed-out' and not manager.slots.active


async def test_policy_alias_works_in_standard_chat_endpoint(network):
    client,manager,router,store,cfg,providers,backends=network
    response=await client.post('/v1/chat/completions',json={'model':'auto','messages':[{'role':'user','content':'hello'}],'max_tokens':4})
    assert response.status_code==200,response.text
    assert response.json()['choices'][0]['message']['content'] in {'one','two'}
    assert (await client.get('/v1/models')).json()['data'][0]['owned_by']=='local-policy'


def test_restart_preserves_results_without_automatic_resubmission(tmp_path):
    store=Store(tmp_path/'jobs.sqlite')
    result={'state':'running','tasks':[{'state':'running','text':'partial'}]}
    store.add_job('job-test','fingerprint',result,8,100)
    store.close()
    store=Store(tmp_path/'jobs.sqlite')
    saved=store.job('job-test')[1]
    assert saved['state']=='interrupted' and saved['tasks'][0]['state']=='interrupted'
    assert saved['tasks'][0]['text']=='partial'
    assert store.db.execute('SELECT sum(tokens) FROM gateway_budget').fetchone()[0]==8


async def test_routing_filters_paid_stale_wrong_model_and_network_targets(network):
    client,manager,router,store,cfg,providers,backends=network
    for ad in store.peers():
        body=ad['body'];body['sequence']+=1;body['offer']['output_msat_per_token']=10
        p=next(p for p in providers if p.identity.public==ad['signer'])
        store.ingest(p.identity.sign(body))
    with pytest.raises(ValueError):router.select('auto',4)
    assert (await client.post('/v1/jobs',json=job())).status_code==409
    assert not any(b.seen for b in backends)


async def test_latency_and_preferred_model_are_buyer_local(network,manifest):
    client,manager,router,store,cfg,providers,backends=network
    store.record_route(providers[0].identity.public,manifest.model_id,500,True)
    store.record_route(providers[1].identity.public,manifest.model_id,10,True)
    cfg.gateway.policies[0].strategy='fastest'
    assert router.select('auto',4).provider==providers[1].identity.public
    store.record_route(providers[1].identity.public,manifest.model_id,None,False)
    assert router.select('auto',4).provider==providers[0].identity.public


@pytest.mark.parametrize('change',[
    {'endpoint':'http://169.254.169.254'},
    {'endpoint':'http://unapproved.internal'},
    {'text_chat':False}, {'available':False}, {'model_id_wrong':True}, {'min_context':9999999},
])
async def test_ineligible_discovery_never_receives_context(network,change):
    client,manager,router,store,cfg,providers,backends=network
    for ad in store.peers():
        body=ad['body'];body['sequence']+=1
        if 'endpoint' in change:body['endpoint']=change['endpoint']
        if 'text_chat' in change:body['offer']['text_chat']=False
        if 'available' in change:body['offer']['available']=False
        if 'model_id_wrong' in change:body['offer']['manifest']['name']='different exact model'
        if 'min_context' in change:cfg.gateway.policies[0].min_context_tokens=change['min_context']
        provider=next(p for p in providers if p.identity.public==ad['signer'])
        store.ingest(provider.identity.sign(body))
    assert (await client.post('/v1/jobs',json=job())).status_code==409
    assert not any(b.seen for b in backends)


async def test_expired_ads_and_request_privacy_cannot_be_bypassed(network):
    client,manager,router,store,cfg,providers,backends=network
    payload=job()
    payload['tasks'][0]['trusted_only']=True
    assert (await client.post('/v1/jobs',json=payload)).status_code==409
    store.db.execute('UPDATE peers SET expires=0');store.db.commit()
    assert (await client.post('/v1/jobs',json=job())).status_code==409


async def test_retry_cannot_take_another_tasks_initial_allowance(network):
    client,manager,router,store,cfg,providers,backends=network
    class Broken:
        async def stream_chat(self,*args):
            raise RuntimeError('no delivery');yield {}
    for p in providers:p.backend=Broken()
    result=await finished(client,(await client.post('/v1/jobs',json=job(max_retries=1))).json()['id'])
    assert result['state']=='partial'
    assert result['attempted_output_tokens']==8
    assert [len(t['attempts']) for t in result['tasks']]==[1,1]


async def test_chat_and_jobs_share_daily_budget(network):
    client,manager,router,store,cfg,providers,backends=network
    cfg.gateway.daily_output_tokens=8
    result=await finished(client,(await client.post('/v1/jobs',json=job())).json()['id'])
    assert result['state']=='complete'
    response=await client.post('/v1/chat/completions',json={'model':'auto','messages':[{'role':'user','content':'hi'}],'max_tokens':1})
    assert response.status_code==429


async def test_chat_and_jobs_share_concurrency(network):
    client,manager,router,store,cfg,providers,backends=network
    cfg.gateway.max_concurrent=1
    entered=asyncio.Event()
    class Slow:
        async def stream_chat(self,*args):
            entered.set();await asyncio.Event().wait();yield {}
    for p in providers:p.backend=Slow()
    jid=(await client.post('/v1/jobs',json=job(max_parallel=1))).json()['id']
    await asyncio.wait_for(entered.wait(),2)
    response=await client.post('/v1/chat/completions',json={'model':'auto','messages':[{'role':'user','content':'hi'}],'max_tokens':1})
    assert response.status_code==429
    await client.post('/v1/jobs/'+jid+'/cancel')
    assert not manager.slots.active


def test_job_and_daily_reservation_commit_atomically(tmp_path):
    import sqlite3
    store=Store(tmp_path/'jobs.sqlite')
    store.db.execute("CREATE TRIGGER reject_job BEFORE INSERT ON jobs BEGIN SELECT RAISE(ABORT,'blocked'); END")
    store.db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        store.add_job('j','f',{'state':'queued','tasks':[]},8,10)
    assert store.db.execute('SELECT count(*) FROM gateway_budget').fetchone()[0]==0


async def test_operator_preferred_model_order_is_not_overridden_by_latency(network,manifest):
    client,manager,router,store,cfg,providers,backends=network
    alternate=manifest.model_copy(update={'name':'alternative'})
    selected_provider=providers[1]
    envelope=next(a for a in store.peers() if a['signer']==selected_provider.identity.public)
    body=envelope['body'];body['sequence']+=1;body['offer']['manifest']=alternate.model_dump()
    store.ingest(selected_provider.identity.sign(body))
    policy=cfg.gateway.policies[0]
    policy.model_ids=[alternate.model_id,manifest.model_id];policy.strategy='preferred-model'
    store.record_route(providers[0].identity.public,manifest.model_id,1,True)
    store.record_route(providers[1].identity.public,alternate.model_id,99999,True)
    assert router.select('auto',4).model_id==alternate.model_id


async def test_client_cancel_does_not_count_as_supplier_failure(network,manifest):
    client,manager,router,store,cfg,providers,backends=network
    entered=asyncio.Event()
    class Slow:
        async def stream_chat(self,*args):
            entered.set();await asyncio.Event().wait();yield {}
    for p in providers:p.backend=Slow()
    jid=(await client.post('/v1/jobs',json=job())).json()['id']
    await asyncio.wait_for(entered.wait(),2)
    await client.post('/v1/jobs/'+jid+'/cancel')
    assert all(store.route_stats(p.identity.public,manifest.model_id) is None for p in providers)
    assert not router.loads
