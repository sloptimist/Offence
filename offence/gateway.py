"""Authenticated, GPU-free buyer API. Production and regtest spending are disabled.

Text chat is the deliberately narrow compatibility contract. Provider addresses,
model identities and quotas come only from the operator's configuration.
"""
import asyncio
from contextlib import aclosing
import hmac
import json
import inspect
import os
import secrets
import time
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

from .client import Buyer
from .models import ChatMessage, Strict


class ChatRequest(Strict):
    model: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    max_tokens: int = Field(default=256, ge=1, le=32768)
    stream: bool = False
    temperature: Literal[0] = 0
    n: Literal[1] = 1


class ManagedStream(StreamingResponse):
    """Release reservations even when headers fail before iteration starts."""
    def __init__(self, content, release, **kwargs):
        super().__init__(content, **kwargs)
        self.release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await self.body_iterator.aclose()
            finally:
                result = self.release()
                if inspect.isawaitable(result):
                    await result


def install_gateway(app, config, identity, store, directory, read_body, transport=None):
    from .routing import Router
    from .jobs import Slots, Jobs, install_jobs
    router = Router(config, store)
    routes = router.routes
    slots = Slots(config)
    active = slots.active
    key = os.getenv("OFFENCE_GATEWAY_API_KEY", "")
    if (routes or router.policies) and len(key) < 32:
        raise ValueError("Gateway routes require an API key of at least 32 characters")
    buyer = Buyer(identity, directory)

    def authenticate(request):
        supplied = request.headers.get("authorization", "")
        if not key or not hmac.compare_digest(supplied.encode(), ("Bearer " + key).encode()):
            raise HTTPException(401, "Gateway authentication required")

    manager = Jobs(config, store, buyer, router, slots, transport)
    app.state.jobs, app.state.router = manager, router
    install_jobs(app, manager, authenticate, read_body)

    @app.get("/v1/models")
    async def models(request: Request):
        authenticate(request)
        return {"object": "list", "data": [
            {"id": r.alias, "object": "model", "created": 0, "owned_by": r.provider,
             "offence": {"model_id": r.model_id, "max_output_tokens": r.max_output_tokens,
                         "capabilities": ["text-chat", "streaming"], "execution_verified": False,
                         "payments": "disabled", "max_msat_per_request": 0}}
            for r in routes.values()] + [
                {"id":p.alias,"object":"model","created":0,"owned_by":"local-policy",
                 "offence":{"model_ids":p.model_ids,"strategy":p.strategy,"privacy":p.privacy,
                             "capabilities":["text-chat","streaming","jobs"],"payments":"disabled",
                             "execution_verified":False}}
                for p in router.policies.values()]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        authenticate(request)
        try:
            req = ChatRequest.model_validate(await read_body(request))
        except ValueError:
            raise HTTPException(400, "Unsupported chat request; only text messages, max_tokens, stream, temperature=0 and n=1 are accepted")
        if req.model not in routes and req.model not in router.policies:
            raise HTTPException(404, "Model alias or policy is not configured")
        limit = routes[req.model].max_output_tokens if req.model in routes else router.policies[req.model].max_output_tokens
        if req.max_tokens > limit:
            raise HTTPException(400, "Output exceeds configured model limit")
        try:
            route = router.select(req.model, req.max_tokens)
        except ValueError:
            raise HTTPException(409, "No eligible provider or output limit exceeded")
        if not config.gateway.allow_free_lab:
            raise HTTPException(412, "Execution proofs unavailable; free lab mode requires operator opt-in")
        if req.max_tokens > route.max_output_tokens:
            raise HTTPException(400, "Output exceeds configured model limit")
        if len(active) >= config.gateway.max_concurrent:
            raise HTTPException(429, "Gateway concurrency limit reached")
        if sum(len(m.content.encode()) for m in req.messages) > 16384:
            raise HTTPException(400, "Chat context exceeds byte limit")
        request_id = "chatcmpl-" + secrets.token_hex(16)
        try:
            store.reserve_gateway(request_id, req.max_tokens, config.gateway.daily_output_tokens)
        except ValueError:
            raise HTTPException(429, "Gateway quota or storage limit reached")
        active.add(request_id)
        router.start(route)
        created = int(time.time())
        # A gateway never passes backend keys, its own bearer, arbitrary parameters,
        # or wallet access to a provider. A nonzero quote fails before acceptance.
        source = buyer.run(route.endpoint, route.provider, route.model_id, "", req.max_tokens, 0,
                           allow_lab=True, transport=transport,
                           tor_proxy=config.tor_proxy if ".onion" in route.endpoint else None,
                           messages=[m.model_dump() for m in req.messages], detailed=True)

        completed = False
        failed = False
        first_ms = None
        started = time.monotonic()
        released = False
        def release():
            nonlocal released
            if not released:
                released = True
                try:
                    if completed or failed:
                        router.finish(route, first_ms, completed)
                    else:
                        router.release(route)
                finally:
                    slots.release(request_id)

        async def events():
            nonlocal completed, first_ms, failed
            try:
                deadline = asyncio.get_running_loop().time() + config.gateway.request_deadline_s
                async with aclosing(source):
                    while True:
                        try:
                            async with asyncio.timeout_at(deadline):
                                event = await anext(source)
                        except StopAsyncIteration:
                            break
                        if event['type'] == 'end':
                            completed = True
                        elif first_ms is None:
                            first_ms = int((time.monotonic()-started)*1000)
                        yield event
            except Exception:
                failed = True
                raise
            finally:
                release()

        stream = events()
        # Fetch first verified delivery before committing successful HTTP headers.
        try:
            first = await anext(stream)
        except Exception:
            await stream.aclose()
            release()
            raise HTTPException(502, "Provider could not start signed delivery; no payment made")

        def chunk(delta, finish=None):
            return {"id": request_id, "object": "chat.completion.chunk", "created": created,
                    "model": req.model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

        async def with_first():
            yield first
            async for event in stream:
                yield event

        if req.stream:
            async def output():
                try:
                    yield "data: " + json.dumps(chunk({"role": "assistant"})) + "\n\n"
                    async for event in with_first():
                        if event["type"] == "end":
                            yield "data: " + json.dumps(chunk({}, event["finish_reason"])) + "\n\n"
                        else:
                            yield "data: " + json.dumps(chunk({"content": event["text"]})) + "\n\n"
                    yield "data: [DONE]\n\n"
                except Exception:
                    yield 'data: {"error":{"type":"provider_error","message":"Inference interrupted; no payment made"}}\n\n'
                finally:
                    await stream.aclose()
            async def close_stream():
                try:
                    await stream.aclose()
                finally:
                    release()
            return ManagedStream(output(), close_stream, media_type="text/event-stream",
                                 headers={"X-Offence-Provider":route.provider,"X-Offence-Model-ID":route.model_id})
        try:
            parts, count, finish = [], 0, "stop"
            async with aclosing(stream):
                async for event in with_first():
                    if event["type"] == "end":
                        finish = event["finish_reason"]
                    else:
                        parts.append(event["text"])
                        count += event["token_count"]
            return JSONResponse({"id": request_id, "object": "chat.completion", "created": created,
                "model": req.model, "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(parts)},
                                                "finish_reason": finish}],
                "offence": {"output_tokens": count, "spent_msat": 0, "execution_verified": False,
                            "provider":route.provider,"model_id":route.model_id}})
        except Exception:
            raise HTTPException(502, "Inference interrupted; no payment made")
        finally:
            release()
