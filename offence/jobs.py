"""Bounded independent subtask waves. The harness plans and combines results."""
import asyncio
from contextlib import aclosing
import time
from urllib.parse import urlsplit
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import Field, model_validator
from .crypto import digest, canonical
from .models import Strict, ChatMessage


class Subtask(Strict):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    model: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    max_tokens: int = Field(default=256, ge=1, le=32768)
    trusted_only: bool = False


class JobRequest(Strict):
    idempotency_key: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,64}$')
    tasks: list[Subtask] = Field(min_length=1, max_length=16)
    max_total_output_tokens: int = Field(ge=1, le=100000)
    max_total_msat: Literal[0] = 0
    max_parallel: int = Field(default=2, ge=1, le=16)
    max_retries: int = Field(default=0, ge=0, le=2)
    deadline_s: int = Field(default=120, ge=1, le=3600)
    proof_policy: Literal['required', 'lab-unverified'] = 'required'

    @model_validator(mode='after')
    def validate_wave(self):
        if len({t.id for t in self.tasks}) != len(self.tasks):
            raise ValueError('Duplicate subtask IDs')
        if sum(t.max_tokens for t in self.tasks) > self.max_total_output_tokens:
            raise ValueError('Job cannot reserve the initial subtask requests')
        if any(sum(len(m.content.encode()) for m in t.messages) > 16384 for t in self.tasks):
            raise ValueError('Subtask context too large')
        return self


class Slots:
    def __init__(self, config):
        self.config, self.active = config, set()
        self.changed = asyncio.Event()

    async def enter(self, key):
        while len(self.active) >= self.config.gateway.max_concurrent:
            self.changed.clear()
            await self.changed.wait()
        self.active.add(key)

    def release(self, key):
        self.active.discard(key)
        self.changed.set()


class Jobs:
    def __init__(self, config, store, buyer, router, slots, transport=None):
        self.config, self.store, self.buyer = config, store, buyer
        self.router, self.slots, self.transport = router, slots, transport
        self.running = {}

    def submit(self, req):
        jid = 'job-' + digest({'key':req.idempotency_key})
        fingerprint = digest(req.model_dump())
        existing = self.store.job(jid)
        if existing:
            if existing[0] != fingerprint:
                raise HTTPException(409, 'Idempotency key already belongs to a different job')
            return existing[1]
        g = self.config.gateway
        if req.proof_policy != 'lab-unverified' or not g.allow_free_lab:
            raise HTTPException(412, 'Execution proof unavailable; only explicitly enabled free lab jobs may run')
        if (req.max_total_output_tokens > g.max_job_tokens or req.max_retries > g.max_job_retries
                or req.deadline_s > g.request_deadline_s or req.max_parallel > g.max_concurrent):
            raise HTTPException(400, 'Job exceeds operator limits')
        if len(self.running) >= g.max_active_jobs:
            raise HTTPException(429, 'Active job limit reached')
        # Preflight every task before disclosing any subtask context or reserving work.
        try:
            for t in req.tasks:
                self.router.select(t.model,t.max_tokens,trusted_only=t.trusted_only)
        except ValueError:
            raise HTTPException(409,'No eligible provider for one or more subtasks')
        result = {'id':jid,'state':'queued','reserved_output_tokens':req.max_total_output_tokens,
                  'attempted_output_tokens':0,'received_output_tokens':0,'spent_msat':0,
                  'execution_verified':False,'tasks':[{'id':t.id,'state':'queued','attempts':[],
                      'text':'','received_output_tokens':0} for t in req.tasks]}
        try:
            self.store.add_job(jid,fingerprint,result,req.max_total_output_tokens,g.daily_output_tokens)
        except ValueError:
            raise HTTPException(429,'Job quota or storage limit reached')
        self.running[jid] = asyncio.create_task(self.run(jid,req,result))
        # Retrieve errors if storage failure prevents a final durable record. Startup
        # marks the unfinished record interrupted; no automatic resubmission occurs.
        self.running[jid].add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        return result

    async def run(self, jid, req, result):
        semaphore = asyncio.Semaphore(req.max_parallel)
        # Initial attempts are reserved ahead of retries, so one failing task cannot
        # consume another task's first attempt. Failed/ambiguous reservations are retained.
        retry_budget = req.max_total_output_tokens - sum(t.max_tokens for t in req.tasks)
        async def execute(task, state):
            nonlocal retry_budget
            excluded = set()
            for attempt_no in range(req.max_retries + 1):
                if attempt_no:
                    if retry_budget < task.max_tokens:
                        break
                    retry_budget -= task.max_tokens
                slot = f'{jid}:{task.id}'
                async with semaphore:
                    await self.slots.enter(slot)
                    route, success, cancelled, first_ms = None, False, False, None
                    started = time.monotonic()
                    try:
                        route = self.router.select(task.model,task.max_tokens,excluded,task.trusted_only)
                        self.router.start(route)
                        state['state'] = 'running'
                        result['attempted_output_tokens'] += task.max_tokens
                        attempt = {'provider':route.provider,'model_id':route.model_id,'state':'running',
                                   'session':None,'received_output_tokens':0}
                        state['attempts'].append(attempt)
                        self.store.save_job(jid,result)
                        proxy = self.config.tor_proxy if urlsplit(route.endpoint).hostname.endswith('.onion') else None
                        source = self.buyer.run(route.endpoint,route.provider,route.model_id,'',task.max_tokens,0,
                            allow_lab=True,transport=self.transport,tor_proxy=proxy,
                            messages=[m.model_dump() for m in task.messages],detailed=True)
                        async with aclosing(source):
                            async for event in source:
                                if event['type'] == 'end':
                                    success = True
                                    state['finish_reason'] = event['finish_reason']
                                    continue
                                if first_ms is None:
                                    first_ms = int((time.monotonic()-started)*1000)
                                # Local records link back to retained signed quote/batches/receipts.
                                attempt['session'] = event.get('session')
                                previous_text = state['text']
                                state['text'] += event['text']
                                count = event['token_count']
                                state['received_output_tokens'] += count
                                attempt['received_output_tokens'] += count
                                result['received_output_tokens'] += count
                                if len(state['text'].encode()) > 65536 or len(canonical(result)) > 1024*1024:
                                    state['text'] = previous_text
                                    raise ValueError('Output byte cap exceeded; signed records retained')
                                self.store.save_job(jid,result)
                        if not success:
                            raise ValueError('Missing completion record')
                        attempt['state'] = state['state'] = 'complete'
                        return
                    except asyncio.CancelledError:
                        cancelled = True
                        state['state'] = 'cancelled'
                        if state['attempts']:
                            state['attempts'][-1]['state'] = 'cancelled'
                        raise
                    except Exception:
                        state['state'] = 'failed'
                        if state['attempts']:
                            state['attempts'][-1]['state'] = 'failed'
                        if route:
                            excluded.add(route.provider)
                    finally:
                        try:
                            if route:
                                if cancelled:
                                    self.router.release(route)
                                else:
                                    self.router.finish(route,first_ms,success)
                            self.store.save_job(jid,result)
                        finally:
                            self.slots.release(slot)
                # Never replay a partially delivered subtask to another provider.
                if state['received_output_tokens']:
                    break
            state['state'] = 'failed'

        try:
            result['state'] = 'running'
            self.store.save_job(jid,result)
            async with asyncio.timeout(req.deadline_s), asyncio.TaskGroup() as group:
                for task,state in zip(req.tasks,result['tasks']):
                    group.create_task(execute(task,state))
            result['state'] = 'complete' if all(t['state']=='complete' for t in result['tasks']) else 'partial'
        except TimeoutError:
            result['state'] = 'timed-out'
        except asyncio.CancelledError:
            result['state'] = 'cancelled'
        except Exception:
            result['state'] = 'failed'
        finally:
            for t in result['tasks']:
                if t['state'] in {'queued','running'}:
                    t['state'] = 'cancelled'
            try:
                self.store.save_job(jid,result)
            finally:
                self.running.pop(jid,None)

    async def cancel(self, jid):
        task = self.running.get(jid)
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            # A task cancelled before its first scheduling turn never runs its finally.
            self.running.pop(jid,None)
            existing = self.store.job(jid)
            if existing and existing[1]['state'] in {'queued','running'}:
                result = existing[1]
                result['state'] = 'cancelled'
                for sub in result['tasks']:
                    if sub['state'] in {'queued','running'}: sub['state']='cancelled'
                self.store.save_job(jid,result)

    async def shutdown(self):
        await asyncio.gather(*(self.cancel(jid) for jid in list(self.running)))


def install_jobs(app,manager,authenticate,read_body):
    @app.post('/v1/jobs',status_code=202)
    async def submit(request:Request):
        authenticate(request)
        try:
            req=JobRequest.model_validate(await read_body(request))
        except ValueError:
            raise HTTPException(400,'Invalid independent-subtask job or unsupported parameter')
        return manager.submit(req)

    @app.get('/v1/jobs/{job_id}')
    async def status(job_id:str,request:Request):
        authenticate(request)
        record=manager.store.job(job_id)
        if not record: raise HTTPException(404,'Unknown job')
        return record[1]

    @app.post('/v1/jobs/{job_id}/cancel')
    async def cancel(job_id:str,request:Request):
        authenticate(request)
        if not manager.store.job(job_id): raise HTTPException(404,'Unknown job')
        await manager.cancel(job_id)
        return manager.store.job(job_id)[1]
