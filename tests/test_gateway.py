import json
import time

import httpx
import pytest

from offence.app import bounded_body, create_app
from offence.backend import Fixture
from offence.crypto import Identity
from offence.gateway import install_gateway
from offence.models import Config, GatewayConfig, GatewayRoute


class ChatFixture(Fixture):
    def stream_chat(self, messages, max_tokens):
        return self.stream('', max_tokens)


def gateway(tmp_path, config, manifest, monkeypatch, paid=False):
    monkeypatch.setenv('OFFENCE_GATEWAY_API_KEY', 'a' * 32)
    if paid:
        config.offer.output_msat_per_token = 1
    provider_app = create_app(tmp_path / 'provider', config, backend=ChatFixture(), background=False)
    provider = provider_app.state.provider
    if paid:
        provider.wallet = object()  # Quotes exist, but accepting them must never occur.
    buyer_config = Config(allowed_private_peers=['http://provider'], gateway=GatewayConfig(allow_free_lab=True,
        daily_output_tokens=16, routes=[GatewayRoute(alias='fixture', endpoint='http://provider',
        provider=provider.identity.public, model_id=manifest.model_id, max_output_tokens=8)]))
    from fastapi import FastAPI
    from offence.store import Store
    store = Store(tmp_path / 'gateway.sqlite')
    app = FastAPI()
    install_gateway(app, buyer_config, Identity(), store, tmp_path / 'buyer', bounded_body,
                    transport=httpx.ASGITransport(app=provider_app))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway',
                              headers={'Authorization': 'Bearer ' + 'a' * 32})
    return client, provider, store, buyer_config


def chat(**changes):
    return {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'Hello'}], 'max_tokens': 8, **changes}


async def test_agent_gets_models_and_signed_free_stream(tmp_path, config, manifest, monkeypatch):
    client, provider, store, cfg = gateway(tmp_path, config, manifest, monkeypatch)
    async with client:
        models = (await client.get('/v1/models')).json()
        assert models['data'][0]['offence']['model_id'] == manifest.model_id
        response = await client.post('/v1/chat/completions', json=chat(stream=True))
        assert response.status_code == 200
        records = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: {')]
        assert ''.join(r['choices'][0]['delta'].get('content', '') for r in records) == 'This is a lab fixture.'
        assert response.text.endswith('data: [DONE]\n\n')
        assert provider.active == 0


async def test_nonstreaming_and_authentication(tmp_path, config, manifest, monkeypatch):
    client, provider, store, cfg = gateway(tmp_path, config, manifest, monkeypatch)
    async with client:
        assert (await client.get('/v1/models', headers={'Authorization': ''})).status_code == 401
        result = await client.post('/v1/chat/completions', json=chat())
        assert result.json()['choices'][0]['message']['content'] == 'This is a lab fixture.'
        assert result.json()['offence']['spent_msat'] == 0


@pytest.mark.parametrize('change', [
    {'tools': [{'type': 'function', 'function': {'name': 'execute_shell'}}]},
    {'backend_url': 'http://169.254.169.254/'},
    {'model': '../../etc/passwd'},
    {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'file:///etc/shadow'}}]}]},
    {'messages': [{'role': 'tool', 'content': 'run arbitrary code'}]},
    {'max_tokens': 999}, {'n': 2}, {'max_tokens': True},
])
async def test_untrusted_parameters_never_reach_supplier(tmp_path, config, manifest, monkeypatch, change):
    client, provider, store, cfg = gateway(tmp_path, config, manifest, monkeypatch)
    async with client:
        response = await client.post('/v1/chat/completions', json=chat(**change))
        assert response.status_code in (400, 404)
        assert provider.store.evidence()['sessions'] == {}


async def test_paid_offer_and_proof_required_fail_closed(tmp_path, config, manifest, monkeypatch):
    client, provider, store, cfg = gateway(tmp_path, config, manifest, monkeypatch, paid=True)
    async with client:
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 502
        assert provider.store.evidence()['sessions'] == {}
        cfg.gateway.allow_free_lab = False
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 412


async def test_daily_reservations_survive_reopening_database(tmp_path, config, manifest, monkeypatch):
    client, provider, store, cfg = gateway(tmp_path, config, manifest, monkeypatch)
    async with client:
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 200
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 200
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 429
    store.close()
    from offence.store import Store
    store = Store(tmp_path / 'gateway.sqlite')
    with pytest.raises(ValueError, match='daily'):
        store.reserve_gateway('after-restart', 1, 16)


def test_gateway_refuses_weak_key_and_unapproved_network(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='DNS'):
        Config(gateway=GatewayConfig(routes=[GatewayRoute(alias='x', endpoint='http://internal',
                        provider='a'*64, model_id='b'*64)]))
    monkeypatch.setenv('OFFENCE_GATEWAY_API_KEY', 'weak')
    config = Config(allowed_private_peers=['http://internal'], gateway=GatewayConfig(routes=[
        GatewayRoute(alias='x', endpoint='http://internal', provider='a'*64, model_id='b'*64)]))
    with pytest.raises(ValueError, match='API key'):
        create_app(tmp_path, config, background=False)


async def test_concurrent_requests_cannot_exceed_gateway_slots(tmp_path, config, manifest, monkeypatch):
    import asyncio
    client, provider, store, cfg = gateway(tmp_path, config, manifest, monkeypatch)
    cfg.gateway.max_concurrent = 1
    entered, finish = asyncio.Event(), asyncio.Event()
    class Slow(ChatFixture):
        async def stream_chat(self, messages, max_tokens):
            entered.set()
            await finish.wait()
            async for group in self.stream('', max_tokens):
                yield group
    provider.backend = Slow()
    async with client:
        pending = asyncio.create_task(client.post('/v1/chat/completions', json=chat()))
        await asyncio.wait_for(entered.wait(), 2)
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 429
        finish.set()
        assert (await pending).status_code == 200
        assert provider.active == 0


async def test_gateway_timeout_releases_capacity_and_backend(tmp_path, config, manifest, monkeypatch):
    import asyncio
    client, provider, store, cfg = gateway(tmp_path, config, manifest, monkeypatch)
    cfg.gateway.request_deadline_s = 1
    closed = []
    class Slow(ChatFixture):
        async def stream_chat(self, messages, max_tokens):
            try:
                await asyncio.Event().wait()
                yield {}
            finally:
                closed.append(True)
    provider.backend = Slow()
    async with client:
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 502
        provider.backend = ChatFixture()
        assert (await client.post('/v1/chat/completions', json=chat())).status_code == 200
        assert closed and provider.active == 0
